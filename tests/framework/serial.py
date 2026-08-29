"""Marker-based command protocol over a QEMU serial socket."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import select
import shlex
import socket
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import ProtocolError, TestFailure


_ANSI_ESCAPE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_FATAL_KERNEL_MARKERS = (
    b"ZSTD-compressed data is corrupt",
    b"Failed to decompress kernel",
    b"Oops: ",
    b"watchdog: BUG: soft lockup",
    b"rcu: INFO: rcu_preempt self-detected stall",
    b"blocked for more than 120 seconds",
    b"Kernel panic - not syncing",
    b"BUG: unable to handle page fault",
    # The acceptance machine's keyboard and tablet are attached to this
    # emulated controller.  Once Linux declares it dead, later QMP input can
    # no longer prove any desktop action even if the shell remains alive.
    b"xHCI host controller not responding, assume dead",
)
_FATAL_DIAGNOSTIC_TERMINATORS = (
    b"---[ end trace",
    b"Kernel panic - not syncing",
    b"---[ end Kernel panic",
)
_KERNEL_CONSOLE_MARKERS = (
    b"Kernel command line:",
    b"Command line:",
    # ``quiet splash`` can suppress the kernel banner. Bash's systemd OSC
    # prompt marker proves both that firmware/GRUB have left and that the
    # debug shell itself is ready to consume input.
    b"servicename=debug-shell.service",
)
_DEBUG_SHELL_READY_MARKER = b"servicename=debug-shell.service"
_DOWNLOAD_CHUNK_BYTES = 24 * 1024
_DOWNLOAD_FRAME_ATTEMPTS = 8
_DOWNLOAD_FILE_ATTEMPTS = 3
_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 768
_UPLOAD_FRAME_ATTEMPTS = 4
_INLINE_SCRIPT_MAX_BYTES = 2048


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    returncode: int


class SerialConsole:
    """Talk to the ephemeral root debug shell enabled by the harness."""

    def __init__(self, path: Path, transcript: Path, timeout: float = 120.0):
        self.path = path
        self.transcript = transcript
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._buffer = bytearray()
        self._fatal_tail = b""
        self._kernel_console_ready = False
        self._debug_shell_ready = False
        self._log = None

    def connect(self) -> None:
        self.transcript.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.transcript.open("ab", buffering=0)
        deadline = time.monotonic() + self.timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            try:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.connect(str(self.path))
                connection.setblocking(False)
                self._socket = connection
                return
            except OSError as error:
                last_error = error
                time.sleep(0.1)
        raise ProtocolError(f"Cannot connect to serial socket: {last_error}")

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def wait_for_shell(self, timeout: float | None = None) -> None:
        """Synchronize only after Linux has taken ownership of the serial port.

        The same UART is visible to firmware, GRUB, the kernel and the debug
        shell.  Sending a shell probe while GRUB's menu is active is not
        harmless: any ``c`` byte opens GRUB's command line and prevents the
        default entry from booting. Use separate passive kernel and Bash-ready
        boundaries; merely seeing systemd start the unit is still too early.
        """

        deadline = time.monotonic() + (timeout or self.timeout)
        self._wait_for_kernel_console(deadline)
        self._wait_for_debug_shell(deadline)
        while time.monotonic() < deadline:
            try:
                result = self.run("true", timeout=min(10.0, deadline - time.monotonic()))
            except ProtocolError:
                self._buffer.clear()
                time.sleep(0.5)
                continue
            if result.returncode == 0:
                self.run(
                    "stty -echo -onlcr < /dev/tty; export LANG=C LC_ALL=C",
                    timeout=10,
                )
                return
        raise ProtocolError("Timed out waiting for the systemd debug shell")

    def _wait_for_kernel_console(self, deadline: float) -> None:
        """Passively wait until input can no longer be consumed by GRUB."""

        if self._kernel_console_ready:
            return
        marker = re.compile(b"|".join(map(re.escape, _KERNEL_CONSOLE_MARKERS)))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError(
                "Timed out waiting for the operating-system serial console"
            )
        try:
            observed = self._read_until(marker, remaining)
            self._kernel_console_ready = True
            if _DEBUG_SHELL_READY_MARKER in observed:
                self._debug_shell_ready = True
        except ProtocolError as error:
            raise ProtocolError(
                "Timed out waiting for Linux/systemd to take ownership of the "
                f"serial console; no command was sent to firmware or GRUB.\n{error}"
            ) from error

    def wait_for_kernel_console(self, timeout: float) -> None:
        """Expose the passive firmware/GRUB-to-Linux hand-off boundary."""

        self._wait_for_kernel_console(time.monotonic() + timeout)

    def _wait_for_debug_shell(self, deadline: float) -> None:
        """Passively prove that Bash, not merely Linux, owns terminal input."""

        if self._debug_shell_ready:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("Timed out waiting for the systemd debug shell")
        try:
            self._read_until(
                re.compile(re.escape(_DEBUG_SHELL_READY_MARKER)),
                remaining,
            )
            self._debug_shell_ready = True
        except ProtocolError as error:
            raise ProtocolError(
                "Timed out waiting for the systemd debug shell readiness "
                "marker; no shell probe was sent"
            ) from error

    def send_bootloader_line(self, value: str) -> None:
        """Send one strictly bounded ASCII command while GRUB owns the UART."""

        if not value or len(value) > 4096:
            raise ProtocolError("Unsafe GRUB command length")
        if re.fullmatch(r"[A-Za-z0-9 ./,=_:@-]+", value) is None:
            raise ProtocolError("Unsafe character in GRUB command")
        self._send(value.encode("ascii") + b"\n")

    def wait_for_text(self, value: str, timeout: float) -> None:
        """Wait for an exact guest/firmware token and consume through it."""

        needle = value.encode("utf-8")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            index = self._buffer.find(needle)
            if index >= 0:
                del self._buffer[: index + len(needle)]
                return
            if self._socket is None:
                raise ProtocolError("Serial socket is not connected")
            ready, _, _ = select.select(
                [self._socket], [], [], min(0.5, deadline - time.monotonic())
            )
            if not ready:
                continue
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ProtocolError("Serial connection closed unexpectedly")
            self._record_chunk(chunk)
        raise ProtocolError(f"Timed out waiting for serial text: {value!r}")

    def run(
        self,
        script: str,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run an arbitrary shell script without shell-quoting it on the wire."""

        if len(script.encode("utf-8")) <= _INLINE_SCRIPT_MAX_BYTES:
            return self._run_inline(script, timeout=timeout, check=check)

        token = uuid.uuid4().hex
        guest_script = f"/tmp/anduinos-serial-run-{token}.sh"
        quoted_guest_script = shlex.quote(guest_script)
        local_script: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="anduinos-serial-run-",
                suffix=".sh",
                delete=False,
            ) as stream:
                stream.write(script)
                local_script = Path(stream.name)
            self.upload(local_script, guest_script, mode=0o700)
            return self._run_inline(
                "set +e\n"
                f"/bin/bash {quoted_guest_script}\n"
                "rc=$?\n"
                f"rm -f {quoted_guest_script}\n"
                "exit \"$rc\"",
                timeout=timeout,
                check=check,
            )
        finally:
            if local_script is not None:
                local_script.unlink(missing_ok=True)
            try:
                self._run_inline(
                    f"rm -f {quoted_guest_script}",
                    timeout=10,
                    check=False,
                )
            except (OSError, ProtocolError):
                pass

    def _run_inline(
        self,
        script: str,
        *,
        timeout: float | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Run one script that is safely below the guest TTY input limit."""

        token = uuid.uuid4().hex
        start = f"__ANDUINOS_BEGIN_{token}__"
        end = f"__ANDUINOS_END_{token}__"
        payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        command = (
            f"printf '{start}\\n'; "
            f"printf '%s' '{payload}' | base64 -d | /bin/bash; "
            f"rc=$?; printf '\\n{end}:%s\\n' \"$rc\"\r\n"
        )
        self._send(command.encode("ascii"))
        raw = self._read_until(
            re.compile(re.escape(end.encode("ascii")) + rb":([0-9]+)\r?\n"),
            timeout or self.timeout,
        )
        clean = _ANSI_ESCAPE.sub(b"", raw).replace(b"\r", b"")
        start_index = clean.rfind(start.encode("ascii"))
        match = re.search(
            re.escape(end.encode("ascii")) + rb":([0-9]+)\n",
            clean,
        )
        if start_index < 0 or match is None:
            raise ProtocolError("Serial command markers were not returned")
        output_start = start_index + len(start)
        stdout = clean[output_start:match.start()].strip(b"\n").decode(
            "utf-8", errors="replace"
        )
        returncode = int(match.group(1))
        result = CommandResult(stdout=stdout, returncode=returncode)
        if check and returncode != 0:
            raise TestFailure(
                f"Guest command failed with {returncode}: {script.splitlines()[0]}\n"
                f"{stdout}"
            )
        return result

    def upload(self, source: Path, destination: str, mode: int = 0o600) -> None:
        """Upload one file through idempotent, verified, TTY-sized frames.

        The debug shell still uses a terminal line discipline.  A Base64
        command approaching the canonical input limit can be truncated under
        slow TCG emulation even when the host socket accepted every byte.
        Keep each command comfortably below that boundary, validate every
        decoded frame before appending it, and make a repeated frame harmless
        when its acknowledgement was lost.
        """

        source = source.resolve(strict=True)
        size = source.stat().st_size
        expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        token = uuid.uuid4().hex
        temporary = f"{destination}.tmp-{token}"
        chunk_file = f"{temporary}.chunk"
        quoted_temporary = shlex.quote(temporary)
        quoted_chunk = shlex.quote(chunk_file)
        quoted_destination = shlex.quote(destination)
        self.run(
            "set -e\n"
            f"rm -f {quoted_chunk}\n"
            f": > {quoted_temporary}"
        )
        try:
            offset = 0
            with source.open("rb") as stream:
                while chunk := stream.read(_UPLOAD_CHUNK_BYTES):
                    data = base64.b64encode(chunk).decode("ascii")
                    digest = hashlib.sha256(chunk).hexdigest()
                    next_offset = offset + len(chunk)
                    script = (
                        "set -euo pipefail\n"
                        f"target={quoted_temporary}\n"
                        f"frame={quoted_chunk}\n"
                        f"offset={offset}\n"
                        f"next={next_offset}\n"
                        f"count={len(chunk)}\n"
                        f"expected={digest}\n"
                        "current=$(stat -c %s \"$target\")\n"
                        "if [ \"$current\" -eq \"$next\" ]; then exit 0; fi\n"
                        "test \"$current\" -eq \"$offset\"\n"
                        "rm -f \"$frame\"\n"
                        f"printf '%s' '{data}' | base64 -d > \"$frame\"\n"
                        "test \"$(stat -c %s \"$frame\")\" -eq \"$count\"\n"
                        "observed=$(sha256sum \"$frame\" | cut -d' ' -f1)\n"
                        "test \"$observed\" = \"$expected\"\n"
                        "cat \"$frame\" >> \"$target\"\n"
                        "rm -f \"$frame\"\n"
                        "test \"$(stat -c %s \"$target\")\" -eq \"$next\""
                    )
                    last_error: Exception | None = None
                    for _attempt in range(_UPLOAD_FRAME_ATTEMPTS):
                        try:
                            result = self.run(script, check=False)
                        except ProtocolError as error:
                            last_error = error
                            continue
                        if result.returncode == 0:
                            break
                        last_error = TestFailure(
                            f"Guest rejected serial upload frame at offset {offset}"
                        )
                    else:
                        raise ProtocolError(
                            "Could not deliver a verified serial upload frame for "
                            f"{source} at offset {offset}"
                        ) from last_error
                    offset = next_offset
            self.run(
                "set -euo pipefail\n"
                f"target={quoted_temporary}\n"
                f"destination={quoted_destination}\n"
                f"test \"$(stat -c %s \"$target\")\" -eq {size}\n"
                "observed=$(sha256sum \"$target\" | cut -d' ' -f1)\n"
                f"test \"$observed\" = {expected_sha256}\n"
                f"chmod {mode:o} \"$target\"\n"
                "mv \"$target\" \"$destination\""
            )
        except BaseException:
            self.run(
                f"rm -f {quoted_temporary} {quoted_chunk}",
                check=False,
            )
            raise

    def download(
        self,
        source: str,
        destination: Path,
        *,
        missing_ok: bool = False,
        max_bytes: int = _DOWNLOAD_MAX_BYTES,
    ) -> bool:
        """Retrieve one immutable guest file through corruption-detecting frames.

        Kernel and systemd messages share the same serial byte stream as the
        debug shell.  A single ``base64 -w0`` response is therefore unsafe:
        an asynchronous console line can be inserted in the middle of its
        payload.  Each bounded frame below carries its offset and SHA-256 and
        is retried independently.  The complete guest file is hashed both
        before and after transfer, and the local temporary file must match
        that identity before it atomically replaces ``destination``.
        """

        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.partial-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            for file_attempt in range(_DOWNLOAD_FILE_ATTEMPTS):
                metadata = self._download_metadata(source)
                if metadata is None:
                    if missing_ok:
                        return False
                    raise TestFailure(f"Guest download source does not exist: {source}")
                size, expected_sha256 = metadata
                if size > max_bytes:
                    raise TestFailure(
                        f"Refusing to download {source}: {size} bytes exceeds the "
                        f"{max_bytes}-byte transfer limit"
                    )
                digest = hashlib.sha256()
                with temporary.open("wb") as stream:
                    offset = 0
                    while offset < size:
                        count = min(_DOWNLOAD_CHUNK_BYTES, size - offset)
                        chunk = self._download_chunk(source, offset, count)
                        stream.write(chunk)
                        digest.update(chunk)
                        offset += len(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                final_metadata = self._download_metadata(source)
                observed_sha256 = digest.hexdigest()
                if (
                    final_metadata == metadata
                    and temporary.stat().st_size == size
                    and observed_sha256 == expected_sha256
                ):
                    os.replace(temporary, destination)
                    return True
                temporary.unlink(missing_ok=True)
                if file_attempt + 1 < _DOWNLOAD_FILE_ATTEMPTS:
                    continue
                raise TestFailure(
                    "Guest file changed or failed its complete SHA-256 during "
                    f"serial download: {source}"
                )
        finally:
            temporary.unlink(missing_ok=True)
        raise AssertionError("serial download retry loop ended unexpectedly")

    def _download_metadata(self, source: str) -> tuple[int, str] | None:
        quoted = shlex.quote(source)
        for _attempt in range(_DOWNLOAD_FRAME_ATTEMPTS):
            token = f"__ANDUINOS_DOWNLOAD_META_{uuid.uuid4().hex}__"
            result = self.run(
                "set -euo pipefail\n"
                f"source={quoted}\n"
                f"token={shlex.quote(token)}\n"
                "if test ! -f \"$source\"; then\n"
                "  printf '%s:missing\\n' \"$token\"\n"
                "else\n"
                "  size=$(stat -c %s \"$source\")\n"
                "  digest=$(sha256sum \"$source\" | cut -d' ' -f1)\n"
                "  printf '%s:present:%s:%s\\n' \"$token\" \"$size\" \"$digest\"\n"
                "fi",
                check=False,
            )
            missing = re.search(
                rf"(?m)^{re.escape(token)}:missing$", result.stdout
            )
            if result.returncode == 0 and missing is not None:
                return None
            match = re.search(
                rf"(?m)^{re.escape(token)}:present:([0-9]+):([0-9a-f]{{64}})$",
                result.stdout,
            )
            if result.returncode == 0 and match is not None:
                return int(match.group(1)), match.group(2)
        raise ProtocolError(
            f"Could not receive an uncorrupted metadata frame for {source}"
        )

    def _download_chunk(self, source: str, offset: int, count: int) -> bytes:
        quoted = shlex.quote(source)
        for _attempt in range(_DOWNLOAD_FRAME_ATTEMPTS):
            token = f"__ANDUINOS_DOWNLOAD_CHUNK_{uuid.uuid4().hex}__"
            result = self.run(
                "set -euo pipefail\n"
                f"source={quoted}\n"
                f"offset={offset}\n"
                f"count={count}\n"
                f"token={shlex.quote(token)}\n"
                "payload=$(dd if=\"$source\" iflag=skip_bytes,count_bytes "
                "skip=\"$offset\" count=\"$count\" status=none | base64 -w0)\n"
                "digest=$(printf '%s' \"$payload\" | base64 -d | "
                "sha256sum | cut -d' ' -f1)\n"
                "printf '%s:%s:%s:%s\\n' \"$token\" \"$offset\" "
                "\"$digest\" \"$payload\"",
                check=False,
            )
            match = re.search(
                rf"(?m)^{re.escape(token)}:{offset}:([0-9a-f]{{64}}):"
                r"([A-Za-z0-9+/]*={0,2})$",
                result.stdout,
            )
            if result.returncode != 0 or match is None:
                continue
            try:
                chunk = base64.b64decode(match.group(2), validate=True)
            except ValueError:
                continue
            if len(chunk) != count:
                continue
            if hashlib.sha256(chunk).hexdigest() != match.group(1):
                continue
            return chunk
        raise ProtocolError(
            "Could not receive an uncorrupted serial download frame for "
            f"{source} at offset {offset}"
        )

    def _send(self, value: bytes) -> None:
        if self._socket is None:
            raise ProtocolError("Serial socket is not connected")
        remaining = memoryview(value)
        deadline = time.monotonic() + self.timeout
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise ProtocolError(
                    f"Timed out writing {len(value)} bytes to serial socket"
                )
            try:
                _, writable, _ = select.select(
                    [], [self._socket], [], min(0.5, wait)
                )
                if not writable:
                    continue
                sent = self._socket.send(remaining)
            except BlockingIOError:
                continue
            except OSError as error:
                raise ProtocolError(
                    f"Cannot write to serial socket: {error}"
                ) from error
            if sent <= 0:
                raise ProtocolError("Serial socket closed while writing")
            remaining = remaining[sent:]

    def _read_until(self, pattern: re.Pattern[bytes], timeout: float) -> bytes:
        if self._socket is None:
            raise ProtocolError("Serial socket is not connected")
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < deadline:
            if pattern.search(self._buffer):
                result = bytes(self._buffer)
                self._buffer.clear()
                return result
            ready, _, _ = select.select(
                [self._socket], [], [], min(0.5, deadline - time.monotonic())
            )
            if not ready:
                continue
            chunk = self._socket.recv(65536)
            if not chunk:
                raise ProtocolError("Serial connection closed unexpectedly")
            self._record_chunk(chunk)
        tail = _ANSI_ESCAPE.sub(b"", bytes(self._buffer[-4096:])).decode(
            "utf-8", errors="replace"
        )
        raise ProtocolError(f"Timed out waiting for serial response; tail:\n{tail}")

    def _record_chunk(self, chunk: bytes) -> None:
        """Persist serial bytes and fail on fatal kernel health with a full trace."""

        if self._log is not None:
            self._log.write(chunk)
        self._buffer.extend(chunk)
        sample = self._fatal_tail + chunk
        marker = _fatal_kernel_marker(sample)
        self._fatal_tail = sample[-256:]
        if marker is not None:
            # Kernel Oops headers and their call traces commonly arrive in
            # separate serial reads.  Reaping QEMU on the first header used to
            # destroy the only useful diagnostic evidence.  Drain only bytes
            # that are already arriving, with a short idle and hard deadline;
            # the fatal verdict remains immediate and can never be downgraded.
            diagnostic = bytearray(sample[-4096:])
            self._drain_fatal_diagnostics(diagnostic)
            clean = _ANSI_ESCAPE.sub(b"", bytes(diagnostic)).replace(b"\r", b"")
            context = clean.decode("utf-8", errors="replace")
            raise TestFailure(
                "Guest kernel emitted fatal serial marker "
                f"{marker!r}; see {self.transcript.name}.\n{context}"
            )

    def _drain_fatal_diagnostics(self, diagnostic: bytearray) -> None:
        if self._socket is None:
            return
        # A heavily loaded guest can pause for several scheduler ticks between
        # the Oops header and the RIP/call trace.  Keep the verdict immediate,
        # but retain a long enough bounded diagnostic window that the useful
        # symbol is not destroyed when QEMU is reaped.
        hard_deadline = time.monotonic() + 5.0
        idle_deadline = time.monotonic() + 1.0
        while time.monotonic() < min(hard_deadline, idle_deadline):
            wait = min(hard_deadline, idle_deadline) - time.monotonic()
            ready, _, _ = select.select([self._socket], [], [], max(0.0, wait))
            if not ready:
                break
            try:
                chunk = self._socket.recv(65536)
            except BlockingIOError:
                continue
            if not chunk:
                break
            if self._log is not None:
                self._log.write(chunk)
            self._buffer.extend(chunk)
            diagnostic.extend(chunk)
            if len(diagnostic) > 1024 * 1024:
                del diagnostic[: len(diagnostic) - 1024 * 1024]
            if any(item in diagnostic for item in _FATAL_DIAGNOSTIC_TERMINATORS):
                break
            idle_deadline = time.monotonic() + 1.0


def _fatal_kernel_marker(value: bytes) -> str | None:
    for marker in _FATAL_KERNEL_MARKERS:
        if marker in value:
            return marker.decode("ascii")
    return None
