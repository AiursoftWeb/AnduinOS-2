"""Fast self-tests for the QEMU acceptance harness itself."""

from __future__ import annotations

import base64
import hashlib
import inspect
import io
import json
import os
import re
import runpy
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from PIL import Image, ImageDraw

from framework.base import PromotedBase, discard_overlay
from framework.errors import ConfigurationError, ProtocolError, TestFailure
from assertions.install import (
    RELEASE_CONTRACT_CHECKS,
    _assert_release_contracts,
    _validate_passwordless_sudo_evidence,
    assert_installed_region,
    assert_live_environment,
    assert_live_identity,
    assert_live_region,
    assert_passwordless_sudo_behavior,
    assert_release_contract,
)
from framework.dashboard import AcceptanceDashboard
from business.acceptance import (
    _materialize_case_results,
    _materialize_suite_results,
    _termination_as_interrupt,
)
from framework.firmware import FirmwareSelection
from framework.feature_model import FeatureSuiteRegistry
from business.desktop import (
    FeatureSuiteRunner,
    _SHELL_DRIVER_CHECKS,
    _validate_account_record,
    _validate_account_creation_events,
    _validate_alt_tab_events,
    _validate_desktop_shortcut_events,
    _validate_desktop_icon_events,
    _validate_desktop_terminal_events,
    _validate_distinct_boot_ids,
    _validate_deb_software_events,
    _validate_gdm_cursor_contract,
    _validate_gdm_login_events,
    _validate_gdm_user_events,
    _validate_graphical_vt_evidence,
    _validate_graphical_login,
    _validate_initial_overview_events,
    _validate_localization_zh_cn_events,
    _validate_nextcloud_ppa_evidence,
    _validate_spotify_public_catalog_evidence,
    _validate_chinese_editor_events,
    _validate_cpu_z_download_evidence,
    _validate_cpu_z_events,
    _validate_image_open_events,
    _validate_password_change_events,
    _validate_password_fingerprint_change,
    _validate_panel_pin_initial_events,
    _validate_panel_pin_persisted_events,
    _validate_panel_pin_roundtrip,
    _validate_panel_remove_events,
    _validate_appindicator_roundtrip_events,
    _validate_rime_evidence,
    _validate_rollback_health,
    _validate_screenshot_shortcut_events,
    _validate_settings_about_events,
    _validate_swapcontrol_events,
    _validate_same_fixture_process,
    _validate_search_provider_preflight,
    _validate_local_search_provider_isolation_configuration,
    _validate_local_search_provider_post_action_isolation,
    _validate_local_search_provider_runtime_isolation,
    _validate_theme_marker,
    _validate_theme_selection,
    _validate_tty6_evidence,
    _validate_thumbnail_events,
    _validate_super_i_events,
    _validate_super_tab_events,
    _validate_super_u_events,
    _validate_video_open_events,
    _validate_spotify_store_events,
    _validate_wechat_install_evidence,
    _validate_wechat_install_events,
    _validate_wechat_tray_events,
    _validate_start_button_contract,
    _validate_start_button_events,
    _graphical_vt_probe_command,
    _join_contract_outputs,
    _cpu_z_download_command,
    _nextcloud_ppa_source_probe_command,
    _spotify_public_catalog_command,
    _wechat_install_command,
    _tty6_probe_command,
)
from framework.grub import (
    _ArmGraphicalGrubCommandLine,
    _GraphicalGrubMenuEditor,
    InstalledBootFiles,
    boot_iso_with_debug_shell,
    debug_kernel_arguments,
    render_installed_grub_instrumentation,
    render_installed_grub_restoration,
    uses_graphical_grub_synchronization,
)
from fixtures.builder import _build_pe, build_file_integration_fixtures
from framework.iso import _parse_live_entries
from framework.model import (
    Architecture,
    Filesystem,
    Firmware,
    LiveMode,
    Network,
    SshPolicy,
    TestMatrix,
)
from framework.qemu import (
    PERSISTENT_LIVE_FREE_SPACE_GIB,
    QemuConfig,
    QemuVm,
    _file_size_limiter,
)
from framework.qmp import QmpClient, _ppm_dimensions
from framework.reporting import write_junit_report
from framework.visual import (
    grub_editor_left_cursor_y,
    grub_editor_layout,
    grub_frame_difference,
    grub_menu_layout,
)
from framework.spice_input import SpiceInputClient
from business.install import (
    _GUEST_QMP_CLICK_SETTLE_SECONDS,
    _GUEST_QMP_KEY_SETTLE_SECONDS,
    _GRAPHICAL_USER_SCRIPT,
    _SUPPORTED_GUEST_QMP_KEYS,
    ScenarioRunner,
    scenario_check_ids,
    _assert_guest_ssh_stopped,
    _desktop_command,
    _guest_qmp_key_supported,
    _login_gdm,
    _is_gnome_extension_entry,
    _parse_qmp_click_request,
    _parse_spice_double_click_request,
    _parse_qmp_key_request,
    _parse_qmp_secret_request,
    _parse_qmp_text_request,
    _resolve_qmp_secret,
    _run_with_qmp_key_requests,
    _ssh_login,
    _power_off,
    _validate_appimage_fixture_contract,
    _validate_appimage_blocked_events,
    _validate_windows_executable_fixture_contract,
    _validate_windows_executable_open_events,
    _validate_windows_executable_thumbnail_events,
    _validate_installer_output,
    _validate_installed_region_ui_events,
    _validate_mok_lifecycle_evidence,
    _validate_target_boot_integrity,
    _validate_uefi_boot_registration_evidence,
)
from framework.serial import CommandResult, SerialConsole, _fatal_kernel_marker
from framework.storage import (
    GIB,
    DiskStorage,
    assert_capacity,
    assert_disk_storage_ready,
    cleanup_disk_storage,
    prepare_disk_storage,
    select_disk_storage,
)
from framework.supervisor import (
    FAULT_LOG_ENV,
    _cleanup_persistent_disks,
    run_supervised_worker,
    supervised_main,
)
from framework.visual import (
    assert_cpu_z_thumbnail,
    assert_font_fixture,
    assert_fixture_quadrants,
    assert_pointer_motion,
    assert_settings_about_logo,
    assert_start_button_logo,
    assert_swapcontrol_green,
    assert_theme_transition,
    assert_wechat_login_window,
    plymouth_match,
)
from framework.wifi import (
    WIFI_LAB_SSID,
    WifiLab,
    _installed_reconnect_script,
    _live_profile_script,
    assert_secret_absent,
    validate_reconnect_evidence,
)


ROOT = Path(__file__).parents[1]


def _source_tree(path: Path) -> str:
    """Read one module or a package as one searchable implementation view."""

    if path.is_file():
        return path.read_text(encoding="utf-8")
    return "\n".join(
        module.read_text(encoding="utf-8")
        for module in sorted(path.rglob("*.py"))
        if "__pycache__" not in module.parts
    )


class _CleanupVm:
    def __init__(self, disk: Path):
        self.config = SimpleNamespace(disk=disk)
        self.running = False
        self.stopped = False

    def create_disk(self):
        self.config.disk.parent.mkdir(parents=True, exist_ok=True)
        self.config.disk.write_bytes(b"partial guest")
        self.running = True

    def create_live_media(self):
        pass

    def stop(self):
        self.running = False
        self.stopped = True


class _FaultyQmp:
    def __init__(self):
        self.close_attempted = False

    def quit(self):
        raise RuntimeError("injected QMP failure")

    def close(self):
        self.close_attempted = True
        raise RuntimeError("injected QMP close failure")


class _ReapProcess:
    def __init__(self):
        self.returncode = None
        self.waited = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waited = True
        self.returncode = 0
        return 0


class _FaultyClose:
    def __init__(self):
        self.close_attempted = False

    def close(self):
        self.close_attempted = True
        raise OSError("injected close failure")


class _FaultyRuntime:
    def __init__(self):
        self.cleanup_attempted = False

    def cleanup(self):
        self.cleanup_attempted = True
        raise OSError("injected runtime cleanup failure")


class _ResultConsole:
    def __init__(self, result):
        self.result = result

    def run(self, *_args, **_options):
        return self.result


class _CaptureConsole:
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _UploadCaptureConsole(SerialConsole):
    def __init__(self):
        self.scripts = []

    def run(self, script, **_options):
        self.scripts.append(script)
        return CommandResult("", 0)


class _DownloadCaptureConsole(SerialConsole):
    def __init__(
        self,
        payload: bytes,
        *,
        corrupt_first_chunk: bool = False,
        corrupt_every_chunk: bool = False,
    ):
        self.payload = payload
        self.corrupt_first_chunk = corrupt_first_chunk
        self.corrupt_every_chunk = corrupt_every_chunk
        self.chunk_calls = 0
        self.corruptions_injected = 0

    def run(self, script, **_options):
        meta = re.search(r"token=(__ANDUINOS_DOWNLOAD_META_[0-9a-f]+__)", script)
        if meta is not None:
            token = meta.group(1)
            digest = hashlib.sha256(self.payload).hexdigest()
            return CommandResult(
                f"{token}:present:{len(self.payload)}:{digest}", 0
            )
        chunk = re.search(
            r"offset=([0-9]+)\ncount=([0-9]+)\n"
            r"token=(__ANDUINOS_DOWNLOAD_CHUNK_[0-9a-f]+__)",
            script,
        )
        if chunk is None:
            raise AssertionError(f"Unexpected download command: {script}")
        offset = int(chunk.group(1))
        count = int(chunk.group(2))
        token = chunk.group(3)
        value = self.payload[offset : offset + count]
        encoded = base64.b64encode(value).decode("ascii")
        digest = hashlib.sha256(value).hexdigest()
        self.chunk_calls += 1
        corrupt = self.corrupt_every_chunk or (
            self.corrupt_first_chunk and self.corruptions_injected == 0
        )
        if corrupt:
            self.corruptions_injected += 1
            midpoint = len(encoded) // 2
            encoded = (
                encoded[:midpoint]
                + "[  117.261164] xhci_hcd: host controller died\n"
                + encoded[midpoint:]
            )
        return CommandResult(f"{token}:{offset}:{digest}:{encoded}", 0)


class FeatureOracleCase(unittest.TestCase):
    @staticmethod
    def _events(*values):
        return "\n".join(json.dumps(value) for value in values)

    @staticmethod
    def _context_action_events(target, label, request_prefix, items, target_index):
        down_presses = target_index + 1
        return [
            {
                "event": "context-menu-plan",
                "target": target,
                "accessible_name": label,
                "items": items,
                "target_index": target_index,
                "down_presses": down_presses,
                "focus_origin": "menu-actor",
            },
            *[
                {
                    "event": "qmp-key",
                    "request": f"{request_prefix}-down-{number}",
                    "key": "down",
                }
                for number in range(1, down_presses + 1)
            ],
            {
                "event": "qmp-key",
                "request": f"{request_prefix}-activate",
                "key": "ret",
            },
            {
                "event": "context-menu-activated",
                "target": target,
                "accessible_name": label,
                "method": "qmp-keyboard",
                "down_presses": down_presses,
            },
        ]

    @staticmethod
    def _context_pointer_events(target, label, request_prefix):
        return [
            {
                "event": "qmp-click",
                "request": f"{request_prefix}-click",
                "target": target,
                "accessible_name": label,
                "button": "left",
                "bounds": [480, 320, 260, 36],
            },
            {
                "event": "context-menu-activated",
                "target": target,
                "accessible_name": label,
                "method": "qmp-pointer",
            },
        ]

    @staticmethod
    def _graphical_vt_output(vt: int = 2) -> str:
        return "\n".join(
            (
                f"active-vt={vt}",
                "graphical-session=3",
                f"graphical-session-vt={vt}",
                "graphical-session-type=wayland",
                "graphical-session-active=yes",
                "graphical-target=active",
                "gdm-service=active",
            )
        )

    @staticmethod
    def _tty6_output(text: str = "AnduinOS 2.0.1 host tty6 login:") -> str:
        return "\n".join(
            (
                "active-vt=6",
                "vcs-device=/dev/vcs6",
                f"vcs-bytes={len(text)}",
                "vcs-sha256=" + "a" * 64,
                "vcs-text-json=" + json.dumps(text),
            )
        )


# Test modules intentionally share this vocabulary.  Keeping it here makes each
# domain file about behavior instead of repeating imports and test doubles.
__all__ = tuple(name for name in globals() if not name.startswith("__"))
