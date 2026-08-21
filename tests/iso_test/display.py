"""Host-driven SPICE display resizing for KVM/virtio desktop acceptance."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .errors import ConfigurationError, TestFailure
from .process_lifecycle import parent_death_preexec


class SpiceDisplayController:
    """Run a real SPICE GTK client on a private X server and resize it."""

    def __init__(self, socket_path: Path, artifacts: Path):
        self.socket_path = socket_path
        self.artifacts = artifacts
        self.display = self._allocate_display()
        self.environment = {**os.environ, "DISPLAY": self.display}
        self.xvfb: subprocess.Popen[bytes] | None = None
        self.viewer: subprocess.Popen[bytes] | None = None
        self.window: str | None = None
        self._viewer_log = None
        self._xvfb_log = None

    @staticmethod
    def required_commands() -> tuple[str, ...]:
        return ("Xvfb", "dbus-run-session", "remote-viewer", "xdotool")

    @classmethod
    def validate_dependencies(cls) -> None:
        missing = [item for item in cls.required_commands() if shutil.which(item) is None]
        if missing:
            raise ConfigurationError(
                "Desktop resolution gate requires: " + ", ".join(missing)
            )

    def start(self) -> None:
        self.validate_dependencies()
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self._xvfb_log = (self.artifacts / "spice-xvfb.log").open("wb")
        self.xvfb = subprocess.Popen(
            (
                "Xvfb",
                self.display,
                "-screen",
                "0",
                "1920x1200x24",
                "-nolisten",
                "tcp",
            ),
            stdin=subprocess.DEVNULL,
            stdout=self._xvfb_log,
            stderr=subprocess.STDOUT,
            preexec_fn=parent_death_preexec(),
        )
        display_number = self.display.removeprefix(":")
        x_socket = Path("/tmp/.X11-unix") / f"X{display_number}"
        self._wait_for(lambda: x_socket.exists(), 15, "private X server")
        self._wait_for(lambda: self.socket_path.exists(), 15, "QEMU SPICE socket")
        self._viewer_log = (self.artifacts / "spice-viewer.log").open("wb")
        connection = self.artifacts / "spice-connection.vv"
        connection.write_text(
            "[virt-viewer]\n"
            "type=spice\n"
            f"unix-path={self.socket_path}\n"
            "delete-this-file=0\n",
            encoding="utf-8",
        )
        self.viewer = subprocess.Popen(
            (
                "dbus-run-session",
                "--",
                "env",
                "GDK_BACKEND=x11",
                "remote-viewer",
                "--title",
                "AnduinOS acceptance display",
                "--zoom",
                "100",
                "--auto-resize=always",
                "--spice-disable-audio",
                "--spice-disable-usbredir",
                str(connection),
            ),
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=self._viewer_log,
            stderr=subprocess.STDOUT,
            preexec_fn=parent_death_preexec(),
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.viewer.poll() is not None:
                raise TestFailure("remote-viewer exited before opening the SPICE display")
            result = subprocess.run(
                (
                    "xdotool",
                    "search",
                    "--onlyvisible",
                    "--name",
                    "AnduinOS acceptance display",
                ),
                env=self.environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            windows = [line for line in result.stdout.splitlines() if line.strip()]
            if windows:
                self.window = windows[-1].strip()
                return
            time.sleep(0.25)
        windows = self._visible_windows()
        (self.artifacts / "spice-x11-windows.txt").write_text(
            windows, encoding="utf-8"
        )
        raise TestFailure(
            "remote-viewer did not expose its SPICE window; inspect "
            "spice-x11-windows.txt and spice-viewer.log"
        )

    def resize(self, width: int, height: int) -> None:
        if self.window is None:
            raise RuntimeError("SPICE viewer has not started")
        result = subprocess.run(
            ("xdotool", "windowsize", self.window, str(width), str(height)),
            env=self.environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise TestFailure("Cannot resize SPICE client: " + result.stdout.strip())

    def stop(self) -> None:
        for process in (self.viewer, self.xvfb):
            if process is None or process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.viewer = None
        self.xvfb = None
        for stream_name in ("_viewer_log", "_xvfb_log"):
            stream = getattr(self, stream_name)
            if stream is not None:
                stream.close()
                setattr(self, stream_name, None)

    def _visible_windows(self) -> str:
        result = subprocess.run(
            ("xdotool", "search", "--onlyvisible", "--name", "."),
            env=self.environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        rows: list[str] = []
        for identifier in result.stdout.splitlines():
            if not identifier.strip().isdigit():
                continue
            title = subprocess.run(
                ("xdotool", "getwindowname", identifier.strip()),
                env=self.environment,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
            ).stdout.strip()
            rows.append(f"{identifier.strip()}\t{title}")
        return "\n".join(rows) + ("\n" if rows else "")

    @staticmethod
    def _wait_for(predicate, timeout: float, label: str) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        raise TestFailure(f"Timed out waiting for {label}")

    @staticmethod
    def _allocate_display() -> str:
        for number in range(90, 190):
            if not (Path("/tmp/.X11-unix") / f"X{number}").exists():
                return f":{number}"
        raise ConfigurationError("No free private X display is available")

    def __enter__(self) -> "SpiceDisplayController":
        self.start()
        return self

    def __exit__(self, _kind, _value, _traceback) -> None:
        self.stop()
