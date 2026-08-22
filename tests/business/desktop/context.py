"""Installed-system feature suites executed on disposable qcow2 overlays."""

from __future__ import annotations

import base64
import json
import hashlib
import re
import shlex
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from PIL import Image, UnidentifiedImageError

from framework.base import PromotedBase, discard_overlay
from assertions.install import assert_release_contract
from assertions.desktop import *  # noqa: F403
from framework.errors import TestFailure
from framework.feature_model import FeatureSuite
from fixtures.builder import build_file_integration_fixtures
from framework.grub import render_installed_grub_restoration
from framework.guest_driver import GuestUiDriver
from assertions.journal import (
    JournalPolicy,
    parse_journal_jsonl,
    parse_package_versions,
    render_guest_collection_script,
    render_verdict,
)
from framework.qemu import QemuVm
from business.install import (
    RunnerOptions,
    _desktop_command,
    _graphical_user,
    _graphical_user_optional,
    _login_gdm,
    _power_off,
    _retrieve_file,
    _retrieve_tree,
    _run_with_qmp_key_requests,
)
from framework.visual import (
    assert_cpu_z_thumbnail,
    assert_wechat_login_window,
    assert_pointer_motion,
    assert_settings_about_logo,
    assert_fixture_quadrants,
    assert_start_button_logo,
    assert_swapcontrol_green,
    assert_theme_transition,
    plymouth_match,
)


_SHELL_DRIVER_CHECKS = frozenset(
    {
        "shell.initial-overview-hidden",
        "shortcut.super-tab",
        "shortcut.alt-tab",
        "shortcut.super-i",
        "branding.settings-about-logo",
        "appearance.swapcontrol-green",
        "shortcut.super-u",
        "shortcut.super-shift-s",
        "branding.start-button-logo",
        "panel.pin-application",
        "panel.remove-menu-localized",
        "shell.appindicator-roundtrip",
        "desktop.icons-visible",
        "desktop.context-menu-terminal",
        "desktop.create-shortcut",
        "search.spotify-store",
        "store.spotify-public",
        "app.wechat-install",
    }
)
_SHORTCUT_FIXTURE_CHECKS = frozenset({"shortcut.alt-tab"})
_PANEL_FIXTURE_CHECKS = frozenset(
    {
        "panel.pin-application",
        "panel.remove-menu-localized",
        "desktop.create-shortcut",
    }
)
_INDICATOR_FIXTURE_CHECKS = frozenset({"shell.appindicator-roundtrip"})
_LOCAL_ARCMENU_SEARCH_CHECKS = frozenset(
    {
        "panel.pin-application",
        "desktop.create-shortcut",
    }
)
_LOCAL_SEARCH_DRIVER_MODES = frozenset(
    {
        "shell-panel-pin",
        "shell-panel-pin-persisted",
        "shell-panel-remove",
        "shell-desktop-shortcut",
    }
)
_SOFTWARE_SEARCH_DRIVER_MODES = frozenset(
    {
        "shell-spotify-store",
        "public-wechat-install",
    }
)


# Domain mixins intentionally share the VM/session vocabulary from this module.
__all__ = tuple(name for name in globals() if not name.startswith("__"))
