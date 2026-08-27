"""End-to-end orchestration for one declarative acceptance scenario."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Callable

from assertions.install import (
    RELEASE_CONTRACT_CHECKS,
    assert_installed_environment,
    assert_installed_region,
    assert_live_environment,
    assert_live_identity,
    assert_live_region,
    assert_no_image_junk,
    assert_passwordless_sudo_behavior,
    assert_release_contract,
)
from framework.base import PromotedBase, _discard_variable_store, promote_base
from framework.errors import ProtocolError, TestFailure
from framework.display import SpiceDisplayController
from fixtures.builder import build_appimage_fixture, build_windows_executable_fixture
from framework.firmware import FirmwareOverrides, copy_variables, resolve_firmware
from framework.grub import (
    InstalledBootFiles,
    boot_iso_with_debug_shell,
    render_installed_grub_instrumentation,
    render_installed_grub_restoration,
)
from framework.guest_driver import GuestUiDriver
from framework.iso import IsoInspection
from assertions.journal import (
    JournalPolicy,
    parse_journal_jsonl,
    parse_package_versions,
    render_guest_collection_script,
    render_verdict,
)
from framework.model import (
    Architecture,
    Firmware,
    LiveMode,
    MatrixDefaults,
    Network,
    Scenario,
    SshPolicy,
)
from framework.qemu import (
    PERSISTENT_LIVE_FREE_SPACE_GIB,
    QemuConfig,
    QemuVm,
    allocate_tcp_port,
    resolve_qemu,
)
from framework.spice_input import SpiceInputClient
from framework.storage import GIB, DiskStorage, assert_disk_storage_ready
from framework.visual import assert_cpu_z_thumbnail, assert_font_fixture, plymouth_match
from framework.wifi import WifiLab, WifiLabState


__all__ = tuple(name for name in globals() if not name.startswith("__"))
