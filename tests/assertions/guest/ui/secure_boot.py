"""First-boot trust oracle: read-only root probe and real user-session UI."""

import gettext
import json
from pathlib import Path
import re
import stat
import subprocess
import time


ROW_STATES = (
    ("Secure Boot", "Motherboard hardware protection is active"),
    ("Local MOK Certificate", "Certificate generated locally"),
    ("Certificate Signing Permissions", "Can sign both GRUB and kernel modules"),
    ("UEFI Firmware Trust", "This certificate is enrolled in MOK"),
    ("Third-party Drivers", "Secure Boot trust is ready. No third-party kernel modules are currently installed."),
)
REPAIR_ACTIONS = (
    "Repair Signing Defaults", "Repair Automatic DKMS Signing", "Repair Module Signatures",
    "Create Unified Certificate", "Submit Enrollment Request", "Recreate Certificate…",
    "Use Enrolled Certificate", "Prepare AnduinOS for Secure Boot", "Enable Secure Boot",
    "Open UEFI Settings", "Check Again",
    "Install AnduinOS Bootloader", "Repair AnduinOS Bootloader",
)


def validate_status(payload):
    state = payload["secure_boot"]
    for field in ("enabled", "key_present", "certificate_present", "enrolled", "configuration_present"):
        if state.get(field) is not True:
            raise ValueError(f"Secure Boot not ready: {field}")
    if state.get("status") != "enabled" or state.get("enrollment_pending") is not False:
        raise ValueError("Secure Boot disabled/unknown or enrollment still pending")
    identity = state["signing_identity"]
    if (identity.get("purpose") != "unified" or identity.get("enrollment") != "enrolled"
            or identity.get("key_present") is not True or identity.get("defaults_ready") is False):
        raise ValueError("Unified signing identity is not usable")
    if payload["dkms"]["untrusted_modules"]:
        raise ValueError("Third-party modules are not trusted")
    boot = state.get("grub", {})
    if (boot.get("installed") is not True or boot.get("signature") != "valid"
            or boot.get("enrollment") != "enrolled" or boot.get("deployment") != "ready"):
        raise ValueError("AnduinOS GRUB is not signed, enrolled and deployed")


def validate_ui(names, translate=lambda value: value):
    """Semantic health contract; screenshot accompanies it, not pixel matching."""
    required = {translate(text) for pair in ROW_STATES for text in pair}
    # The same check also runs in online installations which may have modules.
    if translate("Drivers are signed and ready to load") in names:
        required.discard(translate(ROW_STATES[-1][1]))
    required.add(translate("Trusted"))
    required.update(translate(text) for text in
                    ("AnduinOS Bootloader", "AnduinOS GRUB is signed, trusted and deployed"))
    missing = required - names
    actions = {translate(text) for text in REPAIR_ACTIONS} & names
    if missing or actions:
        raise ValueError(f"Missing healthy states: {sorted(missing)}; unexpected actions: {sorted(actions)}")


def probe_signing_readiness():
    def run(*command):
        return subprocess.check_output(command, text=True, timeout=60).strip()

    payload = json.loads(run("anduinos-securebootctl", "status", "--json"))
    print(json.dumps(payload), flush=True)
    validate_status(payload)
    key = Path("/var/lib/shim-signed/mok/MOK.priv")
    cert = Path("/var/lib/shim-signed/mok/MOK.der")
    info = key.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("Signing private key must be root-owned mode 0600")
    certificate = run("openssl", "x509", "-inform", "DER", "-in", str(cert), "-noout", "-text")
    if ("Code Signing" not in certificate or "Digital Signature" not in certificate
            or "1.3.6.1.4.1.2312.16.1.2" in certificate or "CA:FALSE" not in certificate):
        raise ValueError("Certificate cannot serve as the unified signing certificate")
    run("openssl", "x509", "-inform", "DER", "-in", str(cert), "-noout", "-checkend", "0")
    if run("openssl", "pkey", "-in", str(key), "-pubout") != run(
            "openssl", "x509", "-inform", "DER", "-in", str(cert), "-pubkey", "-noout"):
        raise ValueError("Private key does not match certificate")
    config = Path("/etc/dkms/framework.conf.d/anduinos-sb-sign.conf")
    expected = f'mok_signing_key="{key}"\nmok_certificate="{cert}"\n'
    if config.read_text() != expected:
        raise ValueError("Fresh-install DKMS defaults do not select the new certificate")
    for other in [config.parent.parent / "framework.conf", *config.parent.glob("*.conf")]:
        if other != config and other.exists() and re.search(
                r"^\s*(?:export\s+)?(?:mok_signing_key|mok_certificate|sign_file|sign_tool)\s*=",
                other.read_text(), re.MULTILINE):
            raise ValueError(f"Conflicting DKMS signing override: {other}")
    print("First-boot unified certificate and automatic signing defaults verified.")


def verify_secure_boot_green(evidence):
    from .core import (UiFailure, children, desktop, dismiss_initial_setup,
                       event, name, role, showing, walk)

    translate = gettext.translation("anduinos-driver-center", "/usr/share/locale", fallback=True).gettext
    dismiss_initial_setup()
    with (evidence / "driver-center.log").open("w") as log:
        process = subprocess.Popen(["anduinos-driver-center", "--page", "secure-boot"],
                                   stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 120
    stable_since = None
    reason = "Driver Center has not exposed its window"
    while time.monotonic() < deadline:
        nodes = []
        for app in children(desktop()):
            visible = [item for item in walk(app) if showing(item)]
            if any(name(item) == translate("AnduinOS Driver Center") for item in visible):
                nodes.extend(visible)
        names = {name(item) for item in nodes}
        (evidence / "secure-boot-accessibility.txt").write_text(
            "\n".join(f"{role(item)}\t{name(item)}" for item in nodes), encoding="utf-8")
        try:
            validate_ui(names, translate)
        except ValueError as error:
            stable_since = None
            reason = str(error)
        else:
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since >= 3:
                event("secure-boot-green", rows=6, repair_required=False)
                return
        if process.poll() not in (None, 0):
            raise UiFailure("Driver Center exited; see driver-center.log")
        time.sleep(1)
    raise UiFailure(reason)


if __name__ == "__main__":
    probe_signing_readiness()
