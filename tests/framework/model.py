"""Validated, declarative acceptance-test matrix."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import ConfigurationError


class Architecture(str, Enum):
    AMD64 = "amd64"
    ARM64 = "arm64"


class Firmware(str, Enum):
    BIOS = "bios"
    UEFI_NO_SECURE_BOOT = "uefi-nosb"
    UEFI_SECURE_BOOT = "uefi-sb"

    @property
    def is_uefi(self) -> bool:
        return self is not Firmware.BIOS

    @property
    def secure_boot(self) -> bool:
        return self is Firmware.UEFI_SECURE_BOOT


class Network(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    WIFI = "wifi"


class Filesystem(str, Enum):
    BTRFS = "btrfs"
    EXT4 = "ext4"


class SshPolicy(str, Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    TOGGLE = "toggle"


class LiveMode(str, Enum):
    TEMPORARY = "temporary"
    PERSISTENT = "persistent"


@dataclass(frozen=True)
class MatrixDefaults:
    memory_mib: int
    cpus: int
    disk_gib: int
    boot_timeout_seconds: int
    install_timeout_seconds: int
    command_timeout_seconds: int
    username: str
    full_name: str
    hostname: str
    password: str
    mok_password: str
    live_grub_entry: str
    live_locale: str
    live_timezone: str


@dataclass(frozen=True)
class Scenario:
    id: str
    architectures: tuple[Architecture, ...]
    firmware: Firmware
    network: Network
    filesystem: Filesystem
    live_mode: LiveMode
    rime: bool
    online_features: bool
    ssh: SshPolicy
    passwordless_sudo: bool
    automatic_login: bool
    desktop_contracts: bool
    snapshots_manager: bool
    mok_enrollment: bool

    def supports(self, architecture: Architecture) -> bool:
        return architecture in self.architectures


@dataclass(frozen=True)
class TestMatrix:
    schema_version: int
    defaults: MatrixDefaults
    scenarios: tuple[Scenario, ...]

    @classmethod
    def load(cls, path: Path) -> "TestMatrix":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"Cannot read test matrix: {error}") from error
        if raw.get("schema_version") != 1:
            raise ConfigurationError("Unsupported test matrix schema")
        defaults = _load_defaults(raw.get("defaults"))
        cases = raw.get("cases")
        if not isinstance(cases, list) or not cases:
            raise ConfigurationError("Test matrix has no cases")
        scenarios = tuple(_load_scenario(item) for item in cases)
        identifiers = [item.id for item in scenarios]
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationError("Test matrix contains duplicate case IDs")
        return cls(1, defaults, scenarios)

    def select(
        self,
        architecture: Architecture,
        identifiers: tuple[str, ...] = (),
    ) -> tuple[Scenario, ...]:
        unknown = sorted(set(identifiers) - {item.id for item in self.scenarios})
        if unknown:
            raise ConfigurationError(
                "Unknown test case(s): " + ", ".join(unknown)
            )
        selected = tuple(
            item
            for item in self.scenarios
            if item.supports(architecture)
            and (not identifiers or item.id in identifiers)
        )
        if not selected:
            raise ConfigurationError(
                f"No test cases apply to {architecture.value}"
            )
        return selected


def _load_defaults(value: object) -> MatrixDefaults:
    if not isinstance(value, dict):
        raise ConfigurationError("Test matrix defaults must be an object")
    required = {
        "memory_mib",
        "cpus",
        "disk_gib",
        "boot_timeout_seconds",
        "install_timeout_seconds",
        "command_timeout_seconds",
        "username",
        "full_name",
        "hostname",
        "password",
        "mok_password",
        "live_grub_entry",
        "live_locale",
        "live_timezone",
    }
    if set(value) != required:
        raise ConfigurationError("Test matrix defaults have an invalid shape")
    integer_names = {
        "memory_mib",
        "cpus",
        "disk_gib",
        "boot_timeout_seconds",
        "install_timeout_seconds",
        "command_timeout_seconds",
    }
    for name in integer_names:
        if type(value[name]) is not int or value[name] <= 0:
            raise ConfigurationError(f"Invalid positive integer: defaults.{name}")
    for name in required - integer_names:
        if not isinstance(value[name], str) or not value[name]:
            raise ConfigurationError(f"Invalid string: defaults.{name}")
    return MatrixDefaults(**value)


def _load_scenario(value: object) -> Scenario:
    if not isinstance(value, dict):
        raise ConfigurationError("Every test case must be an object")
    required = {
        "id",
        "architectures",
        "firmware",
        "network",
        "filesystem",
        "live_mode",
        "rime",
        "online_features",
        "ssh",
        "passwordless_sudo",
        "automatic_login",
        "desktop_contracts",
        "snapshots_manager",
        "mok_enrollment",
    }
    if set(value) != required:
        raise ConfigurationError("A test case has an invalid shape")
    identifier = value["id"]
    if not isinstance(identifier, str) or not identifier:
        raise ConfigurationError("Test case ID must be a non-empty string")
    raw_architectures = value["architectures"]
    if not isinstance(raw_architectures, list) or not raw_architectures:
        raise ConfigurationError(f"{identifier}: architectures must be a list")
    try:
        architectures = tuple(Architecture(item) for item in raw_architectures)
        firmware = Firmware(value["firmware"])
        network = Network(value["network"])
        filesystem = Filesystem(value["filesystem"])
        live_mode = LiveMode(value["live_mode"])
        ssh = SshPolicy(value["ssh"])
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{identifier}: invalid enum value") from error
    if len(architectures) != len(set(architectures)):
        raise ConfigurationError(f"{identifier}: duplicate architecture")
    if firmware is Firmware.BIOS and architectures != (Architecture.AMD64,):
        raise ConfigurationError(f"{identifier}: BIOS is amd64-only")
    for name in (
        "rime",
        "online_features",
        "passwordless_sudo",
        "automatic_login",
        "desktop_contracts",
        "snapshots_manager",
        "mok_enrollment",
    ):
        if type(value[name]) is not bool:
            raise ConfigurationError(f"{identifier}: {name} must be boolean")
    if value["online_features"] and network is not Network.ONLINE:
        raise ConfigurationError(
            f"{identifier}: non-Internet case enables downloads"
        )
    if value["rime"] and network is not Network.ONLINE:
        raise ConfigurationError(
            f"{identifier}: non-Internet case enables Rime download"
        )
    if network is Network.WIFI and architectures != (Architecture.AMD64,):
        raise ConfigurationError(
            f"{identifier}: the hwsim test environment is currently amd64-only"
        )
    if live_mode is LiveMode.PERSISTENT and network is Network.WIFI:
        raise ConfigurationError(
            f"{identifier}: persistent-media reboot cannot retain the in-guest Wi-Fi lab"
        )
    if value["mok_enrollment"] != firmware.secure_boot:
        raise ConfigurationError(f"{identifier}: MOK policy contradicts firmware")
    if value["snapshots_manager"] != (filesystem is Filesystem.BTRFS):
        raise ConfigurationError(
            f"{identifier}: snapshot-manager policy contradicts filesystem"
        )
    return Scenario(
        id=identifier,
        architectures=architectures,
        firmware=firmware,
        network=network,
        filesystem=filesystem,
        live_mode=live_mode,
        rime=value["rime"],
        online_features=value["online_features"],
        ssh=ssh,
        passwordless_sudo=value["passwordless_sudo"],
        automatic_login=value["automatic_login"],
        desktop_contracts=value["desktop_contracts"],
        snapshots_manager=value["snapshots_manager"],
        mok_enrollment=value["mok_enrollment"],
    )
