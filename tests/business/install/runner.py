"""One installation scenario coordinated through explicit business phases."""

from .context import *  # noqa: F403
from .access import AccessChecks
from .boot import BootChecks
from .contracts import InstallationContracts
from .desktop import DesktopIntegrationChecks
from .files import FileIntegrationChecks
from .journal import JournalChecks
from .phases import InstallationPhases


class ScenarioRunner(
    AccessChecks,
    BootChecks,
    DesktopIntegrationChecks,
    FileIntegrationChecks,
    InstallationContracts,
    InstallationPhases,
    JournalChecks,
):
    def __init__(
        self,
        inspection: IsoInspection,
        architecture: Architecture,
        defaults: MatrixDefaults,
        options: RunnerOptions,
        status_callback: Callable[[str, str], None] | None = None,
        check_callback: Callable[[str, str, str, str], None] | None = None,
    ):
        self.inspection = inspection
        self.architecture = architecture
        self.defaults = defaults
        self.options = options
        self.driver = GuestUiDriver(Path(__file__).parents[2] / "assertions/guest")
        self.journal_policy = JournalPolicy.load(
            Path(__file__).parents[2] / "assertions/journal-policy.json"
        )
        self.status = status_callback or _status
        self.check_status = check_callback
        self._check_details: dict[tuple[str, str], str] = {}
        self._check_states: dict[str, dict[str, str]] = {}

    @contextmanager
    def _check(self, scenario: Scenario, identifier: str):
        """Emit a child verdict around the exact code that owns the assertion."""

        key = (scenario.id, identifier)
        self._emit_check(scenario.id, identifier, "running", "Running assertions")
        try:
            yield
        except BaseException as error:
            self._emit_check(
                scenario.id,
                identifier,
                "failed",
                f"{type(error).__name__}: {error}",
            )
            self._check_details.pop(key, None)
            raise
        else:
            detail = self._check_details.pop(key, "All assertions passed")
            self._emit_check(scenario.id, identifier, "passed", detail)

    def _check_note(
        self,
        scenario: Scenario,
        identifier: str,
        detail: str,
    ) -> None:
        details = getattr(self, "_check_details", None)
        if details is None:
            details = {}
            self._check_details = details
        details[(scenario.id, identifier)] = detail
        self._emit_check(scenario.id, identifier, "running", detail)

    def _emit_check(
        self,
        scenario_id: str,
        identifier: str,
        state: str,
        detail: str,
    ) -> None:
        plans = getattr(self, "_check_states", {})
        if scenario_id in plans:
            try:
                plans[scenario_id][identifier] = state
            except KeyError as error:
                raise TestFailure(
                    f"{scenario_id}: emitted undeclared child check {identifier!r}"
                ) from error
        callback = getattr(self, "check_status", None)
        if callback is not None:
            callback(scenario_id, identifier, state, detail)

    def run(self, scenario: Scenario, *, promote: bool = False) -> ScenarioResult:
        started = time.monotonic()
        if not hasattr(self, "_check_states"):
            self._check_states = {}
        self._check_states[scenario.id] = {
            identifier: "pending"
            for identifier in scenario_check_ids(scenario)
        }
        artifacts = self.options.artifacts_root / scenario.id
        if artifacts.exists():
            raise TestFailure(f"Refusing to reuse artifact directory: {artifacts}")
        artifacts.mkdir(parents=True)
        # Recheck for every scenario. A previous explicitly retained disk or
        # another host workload must not let a matrix consume the last bytes
        # after the initial CLI preflight. Capacity failures abort the run;
        # they are host safety failures, not product failures.
        assert_disk_storage_ready(
            self.options.disk_storage,
            disk_gib=self.options.disk_gib,
            filesystem_reserve_gib=self.options.free_space_reserve_gib,
            memory_mib=self.options.memory_mib,
            additional_bytes=(
                self.inspection.path.stat().st_size
                + PERSISTENT_LIVE_FREE_SPACE_GIB * GIB
                if scenario.live_mode is LiveMode.PERSISTENT
                else 0
            ),
        )
        vm: QemuVm | None = None
        wifi_lab = WifiLab() if scenario.network is Network.WIFI else None
        passed = False
        base_retained = False
        try:
            vm = self._create_vm(scenario, artifacts)
            vm.create_disk()
            vm.create_live_media()
            self._write_manifest(scenario, vm.config, artifacts)
            boot_files = self._run_live_phase(
                vm,
                scenario,
                artifacts,
                wifi_lab=wifi_lab,
            )
            if boot_files is None:
                raise TestFailure("Installer run did not discover target boot files")
            self._run_target_phase(
                vm,
                scenario,
                boot_files,
                artifacts,
                prepare_overlay_base=promote,
                wifi_lab=wifi_lab,
            )
            self._assert_check_completion(scenario)
            promoted = None
            if promote:
                promoted = promote_base(
                    vm,
                    scenario,
                    self.defaults,
                    self.inspection,
                    boot_files,
                    Path(__file__).parents[2],
                )
                base_retained = True
                (artifacts / "target-disk-retention.txt").write_text(
                    "passed target disk promoted as a temporary immutable "
                    "feature-suite base; it will be deleted after all overlays\n",
                    encoding="utf-8",
                )
            if wifi_lab is not None:
                wifi_lab.assert_not_leaked(artifacts)
            passed = True
            return ScenarioResult(
                scenario.id,
                "passed",
                time.monotonic() - started,
                artifacts,
                promoted_base=promoted,
            )
        except Exception as error:
            if vm is not None and vm.running:
                try:
                    vm.screenshot("failure")
                except Exception:
                    pass
            message = f"{type(error).__name__}: {error}"
            diagnostic = traceback.format_exc()
            if wifi_lab is not None:
                message = message.replace(wifi_lab.password, "<redacted-wifi-secret>")
                diagnostic = diagnostic.replace(
                    wifi_lab.password, "<redacted-wifi-secret>"
                )
            (artifacts / "failure.txt").write_text(
                message + "\n\n" + diagnostic,
                encoding="utf-8",
            )
            if wifi_lab is not None:
                try:
                    wifi_lab.assert_not_leaked(artifacts)
                except Exception as leak_error:
                    error = leak_error
                    message = f"{type(leak_error).__name__}: {leak_error}"
                    (artifacts / "failure.txt").write_text(
                        message + "\n",
                        encoding="utf-8",
                    )
            return ScenarioResult(
                scenario.id,
                "failed",
                time.monotonic() - started,
                artifacts,
                message,
            )
        finally:
            if vm is not None:
                try:
                    vm.stop()
                finally:
                    # Delete only after stop has either reaped QEMU or exposed
                    # that it is still running. `_finalize_disk` refuses the
                    # latter instead of unlinking a live block device.
                    if not base_retained:
                        self._finalize_disk(vm, artifacts, passed=passed)

    def _assert_check_completion(self, scenario: Scenario) -> None:
        incomplete = [
            f"{identifier}={state}"
            for identifier, state in self._check_states[scenario.id].items()
            if state != "passed"
        ]
        if incomplete:
            raise TestFailure(
                "Scenario reached the end without passing every declared child "
                "check: " + ", ".join(incomplete)
            )

    def _finalize_disk(
        self,
        vm: QemuVm,
        artifacts: Path,
        *,
        passed: bool,
    ) -> None:
        if vm.running:
            raise TestFailure("Cannot finalize a target disk while QEMU is running")
        outcome = "passed" if passed else "failed"
        live_media = getattr(vm.config, "live_media", None)
        if live_media is not None and live_media.exists():
            if live_media.name != "live-media.raw" or live_media.is_symlink():
                raise ConfigurationError(
                    f"Refusing unexpected persistent Live-media cleanup target: {live_media}"
                )
            live_media.unlink()
        keep = (
            self.options.keep_passed_disk
            if passed
            else self.options.keep_failed_disk
        )
        if keep:
            message = (
                f"{outcome} target disk and its UEFI variables retained by "
                "explicit single-case option\n"
            )
        elif vm.config.disk.exists():
            vm.config.disk.unlink()
            _discard_variable_store(getattr(vm.config, "variables", None))
            message = (
                f"{outcome} target disk discarded; disposable UEFI variables "
                "discarded; durable logs, compressed screenshots, serial "
                "transcripts, and structured evidence remain\n"
            )
        else:
            _discard_variable_store(getattr(vm.config, "variables", None))
            message = f"{outcome} target disk was never created\n"
        if self.options.disk_storage.is_ramdisk:
            try:
                vm.config.disk.parent.rmdir()
            except OSError:
                pass
        (artifacts / "target-disk-retention.txt").write_text(
            message, encoding="utf-8"
        )

    def _create_vm(self, scenario: Scenario, artifacts: Path) -> QemuVm:
        selection = resolve_firmware(
            self.architecture,
            scenario.firmware,
            self.options.firmware_overrides,
        )
        variables = None
        if selection is not None:
            variables = copy_variables(selection, artifacts / "uefi-vars.fd")
        qemu_binary, acceleration = resolve_qemu(self.architecture)
        config = QemuConfig(
            architecture=self.architecture,
            firmware=scenario.firmware,
            network=scenario.network,
            memory_mib=self.options.memory_mib,
            cpus=self.options.cpus,
            disk_gib=self.options.disk_gib,
            ssh_forward_port=allocate_tcp_port(),
            iso=self.inspection.path,
            disk=self.options.disk_storage.root / scenario.id / "target.qcow2",
            variables=variables,
            firmware_selection=selection,
            artifacts=artifacts,
            qemu_binary=qemu_binary,
            acceleration=acceleration,
            file_size_limit_bytes=self.options.disk_storage.qcow_limit_bytes,
            live_media=(
                self.options.disk_storage.root / scenario.id / "live-media.raw"
                if scenario.live_mode is LiveMode.PERSISTENT
                else None
            ),
        )
        return QemuVm(config)

    def _write_manifest(
        self,
        scenario: Scenario,
        config: QemuConfig,
        artifacts: Path,
    ) -> None:
        value = {
            "iso": str(self.inspection.path),
            "iso_sha256": self.inspection.sha256,
            "architecture": self.architecture.value,
            "scenario": _scenario_json(scenario),
            "qemu": {
                "binary": config.qemu_binary,
                "acceleration": config.acceleration,
                "memory_mib": config.memory_mib,
                "cpus": config.cpus,
                "disk_gib": config.disk_gib,
                "disk_backend": self.options.disk_storage.backend,
                "disk_workspace": str(self.options.disk_storage.root),
                "disk_backend_reason": self.options.disk_storage.reason,
                "disk_file_size_limit_bytes": config.file_size_limit_bytes,
                "ssh_forward_port": config.ssh_forward_port,
                "live_media": (
                    str(config.live_media) if config.live_media is not None else None
                ),
                "live_media_size_bytes": (
                    config.live_media.stat().st_size
                    if config.live_media is not None
                    else None
                ),
                "firmware_code": (
                    str(config.firmware_selection.code)
                    if config.firmware_selection is not None
                    else None
                ),
                "firmware_vars_template": (
                    str(config.firmware_selection.variables_template)
                    if config.firmware_selection is not None
                    else None
                ),
            },
        }
        (artifacts / "manifest.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
