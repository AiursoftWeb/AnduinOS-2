"""Shared installation business vocabulary and declarative check plan."""

from .shared import *  # noqa: F403
from .evidence import *  # noqa: F403
from .guest import *  # noqa: F403
from .protocol import *  # noqa: F403


@dataclass(frozen=True)
class RunnerOptions:
    artifacts_root: Path
    disk_storage: DiskStorage
    firmware_overrides: FirmwareOverrides
    memory_mib: int
    cpus: int
    disk_gib: int
    boot_timeout_seconds: int
    install_timeout_seconds: int
    command_timeout_seconds: int
    firmware_delay_seconds: float
    free_space_reserve_gib: int = 10
    keep_passed_disk: bool = False
    keep_failed_disk: bool = False


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    status: str
    seconds: float
    artifacts: Path
    error: str = ""
    promoted_base: PromotedBase | None = None


def scenario_check_ids(scenario: Scenario) -> tuple[str, ...]:
    """Declare exactly the assertion boundaries emitted for one scenario."""

    checks = [
        "regional.grub-contract",
        "live-boot",
        "live.identity-contract",
        (
            "live.persistent-overlay"
            if scenario.live_mode is LiveMode.PERSISTENT
            else "live.temporary-overlay"
        ),
        "packages.live-image-junk-absent",
        "regional.grub-live-propagation",
        "installer-ui",
        "target-boot-files",
    ]
    if scenario.mok_enrollment:
        checks.append("mok-manager-workflow")
    checks.append("installed-boot")
    if scenario.mok_enrollment:
        checks.append("mok-enrollment")
    if scenario.network is Network.WIFI:
        checks.append("network.wifi-migration-hwsim")
    checks.extend(
        (
            "installed-contracts",
            _passwordless_sudo_check_id(scenario),
            _automatic_login_check_id(scenario),
            "regional.installed-zh-cn",
            "theme.cursor-user-session",
        )
    )
    installed_index = checks.index("installed-contracts") + 1
    checks[installed_index:installed_index] = RELEASE_CONTRACT_CHECKS
    if scenario.desktop_contracts:
        checks.extend(
            (
                "render.twemoji-water-pistol",
                "files.appimage-open",
                "files.exe-thumbnail-fixture",
                "files.exe-open-fixture",
                "shell.extension-policy",
                "shell.extension-errors",
                "display.spice-resize",
            )
        )
    if scenario.snapshots_manager:
        checks.append("snapshots-manager")
    checks.append("host-ssh")
    if scenario.ssh is SshPolicy.TOGGLE:
        checks.append("gnome-ssh-toggle")
    if scenario.desktop_contracts:
        checks.extend(
            (
                "journal.action-scoped",
                "journal.boot-and-idle",
                "boot.plymouth-anduinos-logo",
            )
        )
    return tuple(checks)


def _automatic_login_check_id(scenario: Scenario) -> str:
    return (
        "login.autologin-enabled"
        if scenario.automatic_login
        else "login.autologin-disabled"
    )


def _passwordless_sudo_check_id(scenario: Scenario) -> str:
    return (
        "sudo.passwordless-enabled"
        if scenario.passwordless_sudo
        else "sudo.password-required"
    )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
