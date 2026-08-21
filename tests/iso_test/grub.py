"""Boot through the product GRUB entries with reversible test instrumentation."""

from __future__ import annotations

import shlex
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import ProtocolError
from .model import Architecture
from .qmp import QmpClient
from .serial import SerialConsole
from .spice_input import SpiceInputClient
from .visual import (
    GrubMenuLayout,
    grub_editor_left_cursor_y,
    grub_editor_layout,
    grub_frame_difference,
    grub_menu_layout,
)


@dataclass(frozen=True)
class InstalledBootFiles:
    """Exact target-owned kernel paths discovered after installation."""

    kernel: str
    initrd: str


def debug_kernel_arguments(architecture: Architecture) -> str:
    tty = "ttyS0" if architecture is Architecture.AMD64 else "ttyAMA0"
    return (
        f" console={tty},115200"
        f" systemd.mask=serial-getty@{tty}.service"
        f" systemd.debug_shell={tty}"
    )


def uses_graphical_grub_synchronization(architecture: Architecture) -> bool:
    """Only native/KVM amd64 has responsive pre-kernel QMP screenshots."""

    return architecture is Architecture.AMD64


def boot_iso_with_debug_shell(
    qmp: QmpClient,
    console: SerialConsole,
    architecture: Architecture,
    *,
    firmware_delay: float,
    menu_entry_index: int,
    kernel_arguments: tuple[str, ...] = (),
    spice_socket: Path | None = None,
) -> None:
    """Edit and boot the ISO's real locale menuentry.

    AMD64 follows the same menuentry a user boots and appends only the serial
    test channel in GRUB's editor. ARM64 uses an agent-independent SPICE
    keyboard and requires a stable graphical command-line repaint after every
    command. Linux then proves the complete sequence on the native PL011 while
    the GPU stays present for GNOME.
    """

    if not 0 <= menu_entry_index < 28:
        raise ProtocolError(f"Unsafe ISO GRUB menu index: {menu_entry_index}")
    if uses_graphical_grub_synchronization(architecture):
        time.sleep(firmware_delay)
        editor = _GraphicalGrubMenuEditor(qmp)
        try:
            editor.wait_for_top_menu(timeout=30)
            editor.cancel_timeout()
            editor.enter_language_submenu()
            for _ in range(menu_entry_index):
                editor.move_selection_down()
            editor.open_editor()
            # Each ISO locale entry has setparams, a blank row, gfxpayload,
            # linux and initrd. Three Down presses place the cursor on linux;
            # End moves to the logical line end even when it wraps visually.
            for _ in range(3):
                editor.move_editor_cursor_down()
            editor.move_editor_cursor_to_end()
            editor.type_text_verified(debug_kernel_arguments(architecture))
            qmp.send_key("f10", hold_ms=150)
        finally:
            editor.close()
        return

    if spice_socket is None:
        raise ProtocolError("ARM GRUB requires its private SPICE input channel")
    arguments = tuple(
        item for item in kernel_arguments if item not in {"quiet", "splash", "---"}
    )
    if not arguments:
        arguments = ("boot=casper", "nopersistent")
    commands = (
        "linux /casper/vmlinuz "
        + " ".join(arguments)
        + debug_kernel_arguments(architecture),
        "initrd /casper/initrd",
    )
    started = time.monotonic()
    console.wait_for_text("BdsDxe: starting Boot", timeout=120)
    remaining_delay = firmware_delay - (time.monotonic() - started)
    if remaining_delay > 0:
        time.sleep(remaining_delay)
    keyboard = SpiceInputClient(spice_socket, timeout=30)
    keyboard.connect(require_agent=False)
    command_line = _ArmGraphicalGrubCommandLine(qmp, keyboard)
    try:
        command_line.open(timeout=120)
        for command in commands:
            command_line.submit(command, timeout=120)
        command_line.boot()
    finally:
        command_line.close()
        keyboard.close()
    console.wait_for_kernel_console(timeout=120)


def render_installed_grub_instrumentation(
    architecture: Architecture,
    *,
    mounted_target: bool,
) -> str:
    """Render a fail-closed, reversible edit of generated installed GRUB."""

    root_assignment = (
        'acceptance_root="$mountpoint"' if mounted_target else "acceptance_root=/"
    )
    suffix = shlex.quote(debug_kernel_arguments(architecture))
    return f"""
set -euo pipefail
{root_assignment}
cfg="${{acceptance_root%/}}/boot/grub/grub.cfg"
backup="$cfg.anduinos-acceptance-original"
temporary="$cfg.anduinos-acceptance-new"
test -s "$cfg"
test ! -e "$backup"
test ! -e "$temporary"
! grep -Fq 'systemd.debug_shell=' "$cfg"
cp --preserve=mode,ownership,timestamps "$cfg" "$backup"
suffix={suffix}
awk -v suffix="$suffix" '
    /^[[:space:]]*linux[[:space:]]/ {{ print $0 suffix; next }}
    {{ print }}
' "$backup" > "$temporary"
chmod --reference="$backup" "$temporary"
chown --reference="$backup" "$temporary"
original_linux=$(grep -Ec '^[[:space:]]*linux[[:space:]]' "$backup")
instrumented_linux=$(grep -Ec '^[[:space:]]*linux[[:space:]].*systemd[.]debug_shell=' "$temporary")
test "$original_linux" -gt 0
test "$instrumented_linux" -eq "$original_linux"
mv "$temporary" "$cfg"
grub-script-check "$cfg"
printf 'original-sha256=%s\n' "$(sha256sum "$backup" | awk '{{print $1}}')"
printf 'instrumented-sha256=%s\n' "$(sha256sum "$cfg" | awk '{{print $1}}')"
printf 'instrumented-linux-lines=%s\n' "$instrumented_linux"
grep -E '^[[:space:]]*linux[[:space:]].*systemd[.]debug_shell=' "$cfg" \
    | sed 's/^/instrumented-entry=/'
sync
"""


def render_installed_grub_restoration(*, mounted_target: bool = False) -> str:
    """Render byte-for-byte restoration after the serial shell is available."""

    root_assignment = (
        'acceptance_root="$mountpoint"' if mounted_target else "acceptance_root=/"
    )
    return f"""
set -euo pipefail
{root_assignment}
cfg="${{acceptance_root%/}}/boot/grub/grub.cfg"
backup="$cfg.anduinos-acceptance-original"
temporary="$cfg.anduinos-acceptance-new"
test -s "$cfg"
test -s "$backup"
instrumented_sha256=$(sha256sum "$cfg" | awk '{{print $1}}')
original_sha256=$(sha256sum "$backup" | awk '{{print $1}}')
rm -f "$temporary"
mv "$backup" "$cfg"
grub-script-check "$cfg"
! grep -Fq 'systemd.debug_shell=' "$cfg"
restored_sha256=$(sha256sum "$cfg" | awk '{{print $1}}')
test "$restored_sha256" = "$original_sha256"
grub-editenv "${{acceptance_root%/}}/boot/grub/grubenv" unset recordfail menu_show_once
printf 'instrumented-sha256=%s\n' "$instrumented_sha256"
printf 'restored-sha256=%s\n' "$restored_sha256"
printf 'byte-for-byte-restored=yes\n'
sync
"""


class _ArmGraphicalGrubCommandLine:
    """Gate blind SPICE key delivery with semantic framebuffer repainting."""

    def __init__(self, qmp: QmpClient, keyboard: SpiceInputClient):
        self.qmp = qmp
        self.keyboard = keyboard
        self._temporary = tempfile.TemporaryDirectory(prefix="anduinos-arm-grub-")
        self._counter = 0
        self.current_frame: Path | None = None

    def close(self) -> None:
        self._temporary.cleanup()

    def capture(self) -> Path:
        self._counter += 1
        destination = Path(self._temporary.name) / f"frame-{self._counter:04d}.ppm"
        self.qmp.screendump(destination)
        return destination

    def open(self, *, timeout: float) -> None:
        # Escape cancels the countdown and normalizes a nested menu. The next
        # key opens the graphical command line; no guest agent is involved.
        self.keyboard.send_boot_key("esc")
        self.keyboard.send_boot_key("c")
        self._wait_for_stable_prompt(timeout=timeout, changed_from=None)

    def submit(self, command: str, *, timeout: float) -> None:
        if self.current_frame is None:
            raise ProtocolError("ARM GRUB command line was not synchronized")
        before = self.current_frame
        self.keyboard.type_boot_text(command)
        self.keyboard.send_boot_key("ret")
        self._wait_for_stable_prompt(timeout=timeout, changed_from=before)

    def boot(self) -> None:
        if self.current_frame is None:
            raise ProtocolError("ARM GRUB command line was not synchronized")
        self.keyboard.type_boot_text("boot")
        self.keyboard.send_boot_key("ret")

    def _wait_for_stable_prompt(
        self,
        *,
        timeout: float,
        changed_from: Path | None,
    ) -> None:
        deadline = time.monotonic() + timeout
        previous: Path | None = None
        stable_frames = 0
        while time.monotonic() < deadline:
            frame = self.capture()
            # Menus and entry editors have strong border geometry. A command
            # line has neither; rejecting both prevents an ignored `c` key or
            # accidental `e` shortcut from releasing the next command.
            if (
                grub_menu_layout(frame) is not None
                or grub_editor_layout(frame) is not None
            ):
                previous = None
                stable_frames = 0
                time.sleep(0.1)
                continue
            if (
                changed_from is not None
                and grub_frame_difference(changed_from, frame) < 64
            ):
                previous = frame
                stable_frames = 0
                time.sleep(0.1)
                continue
            if previous is not None and grub_frame_difference(previous, frame) <= 200:
                stable_frames += 1
            else:
                stable_frames = 1
            previous = frame
            if stable_frames >= 3:
                self.current_frame = frame
                return
            time.sleep(0.1)
        raise ProtocolError("Timed out waiting for a stable ARM GRUB command prompt")


class _GraphicalGrubMenuEditor:
    """Synchronize menu/editor transitions through QEMU screendumps."""

    def __init__(self, qmp: QmpClient):
        self.qmp = qmp
        self._temporary = tempfile.TemporaryDirectory(prefix="anduinos-grub-menu-")
        self._counter = 0
        self.current_frame: Path | None = None
        self._editor_cursor_y: int | None = None

    def close(self) -> None:
        self._temporary.cleanup()

    def capture(self) -> Path:
        self._counter += 1
        destination = Path(self._temporary.name) / f"frame-{self._counter:04d}.ppm"
        self.qmp.screendump(destination)
        return destination

    def wait_for_top_menu(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        stable_frames = 0
        previous_menu: Path | None = None
        previous_layout: GrubMenuLayout | None = None
        while time.monotonic() < deadline:
            frame = self.capture()
            layout = grub_menu_layout(frame)
            if layout is not None and layout.visible_unselected_entries <= 6:
                if (
                    previous_menu is not None
                    and previous_layout is not None
                    and layout.highlight_center == previous_layout.highlight_center
                    and grub_frame_difference(previous_menu, frame) <= 20
                ):
                    stable_frames += 1
                else:
                    stable_frames = 1
                previous_menu = frame
                previous_layout = layout
                if stable_frames >= 3:
                    self.current_frame = frame
                    self._editor_cursor_y = None
                    return
            else:
                stable_frames = 0
                previous_menu = None
                previous_layout = None
            time.sleep(0.1)
        raise ProtocolError("Timed out waiting for a stable top-level GRUB menu")

    def enter_language_submenu(self) -> None:
        if self.current_frame is None:
            raise ProtocolError("Graphical GRUB menu was not synchronized")
        self.qmp.send_key("ret")
        # shim's signed GRUB path can spend more than ten seconds loading the
        # 5 MiB AnduinOS Unicode font and painting the 28-entry locale menu.
        # This remains a semantic wait: only the complete, multi-entry submenu
        # releases the next input, regardless of how quickly it is rendered.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = self.capture()
            layout = grub_menu_layout(frame)
            if layout is not None and layout.visible_unselected_entries >= 8:
                self.current_frame = frame
                return
            time.sleep(0.1)
        raise ProtocolError("GRUB did not enter the language submenu")

    def cancel_timeout(self) -> None:
        """Cancel GRUB's countdown and restore the first top-level entry."""

        if self.current_frame is None:
            raise ProtocolError("Graphical GRUB menu was not synchronized")
        original = grub_menu_layout(self.current_frame)
        if original is None or original.visible_unselected_entries > 6:
            raise ProtocolError("Current framebuffer is not the top GRUB menu")
        self.qmp.send_key("down")
        moved = self._wait_for_top_menu_highlight(
            lambda layout: layout.highlight_center != original.highlight_center,
            "GRUB top-level selection did not move while cancelling its timeout",
        )
        self.qmp.send_key("up")
        restored = self._wait_for_top_menu_highlight(
            lambda layout: layout.highlight_center == original.highlight_center,
            "GRUB top-level selection was not restored after cancelling its timeout",
        )
        if moved.highlight_center == restored.highlight_center:
            raise ProtocolError("GRUB timeout cancellation did not traverse two entries")

    def _wait_for_top_menu_highlight(self, predicate, error: str) -> GrubMenuLayout:
        # The signed GRUB path has taken 6-12 seconds to repaint one accepted
        # key under KVM.  Continue polling the semantic highlight rather than
        # treating that latency as lost input or using a fixed sleep.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = self.capture()
            layout = grub_menu_layout(frame)
            if (
                layout is not None
                and layout.visible_unselected_entries <= 6
                and predicate(layout)
            ):
                self.current_frame = frame
                return layout
            time.sleep(0.1)
        raise ProtocolError(error)

    def move_selection_down(self) -> None:
        if self.current_frame is None:
            raise ProtocolError("Graphical GRUB submenu was not synchronized")
        previous = grub_menu_layout(self.current_frame)
        if previous is None:
            raise ProtocolError("Current framebuffer is not a GRUB menu")
        self.qmp.send_key("down")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = self.capture()
            layout = grub_menu_layout(frame)
            if (
                layout is not None
                and layout.visible_unselected_entries >= 8
                and layout.highlight_center != previous.highlight_center
            ):
                self.current_frame = frame
                return
            time.sleep(0.1)
        raise ProtocolError("GRUB language selection did not move")

    def open_editor(self) -> None:
        if self.current_frame is None:
            raise ProtocolError("Graphical GRUB submenu was not synchronized")
        before = self.current_frame
        self.qmp.send_key("e")
        deadline = time.monotonic() + 30
        stable_frames = 0
        previous_editor: Path | None = None
        while time.monotonic() < deadline:
            frame = self.capture()
            layout = grub_editor_layout(frame)
            # The entry has four logical commands, but a locale/timezone-rich
            # linux line may occupy two or more visual rows.  The editor
            # oracle already rejects blank and crowded menu frames; requiring
            # exactly four visual text bands creates a resolution-dependent
            # false failure.
            if layout is not None and layout.visible_command_lines >= 4:
                if (
                    previous_editor is not None
                    and grub_frame_difference(previous_editor, frame) <= 20
                ):
                    stable_frames += 1
                else:
                    stable_frames = 1
                previous_editor = frame
                if (
                    stable_frames >= 3
                    and grub_frame_difference(before, frame) >= 100
                ):
                    self.current_frame = frame
                    self._editor_cursor_y = None
                    return
            else:
                stable_frames = 0
                previous_editor = None
            time.sleep(0.1)
        raise ProtocolError(
            "GRUB did not paint a stable complete menuentry editor"
        )

    def move_editor_cursor_down(self) -> None:
        if self.current_frame is None:
            raise ProtocolError("GRUB editor was not synchronized")
        if grub_editor_layout(self.current_frame) is None:
            raise ProtocolError("Current framebuffer is not a GRUB editor")
        if self._editor_cursor_y is None:
            # The underline cursor blinks.  Observe its actual pre-key
            # position first; otherwise the unchanged old cursor can be
            # mistaken for an acknowledgement of the first Down press.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                frame = self.capture()
                observed = grub_editor_left_cursor_y(frame)
                if observed is not None:
                    self.current_frame = frame
                    self._editor_cursor_y = observed
                    break
                time.sleep(0.05)
            else:
                raise ProtocolError("GRUB editor cursor was not visible before Down")
        previous_y = self._editor_cursor_y
        assert previous_y is not None
        self.qmp.send_key("down")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = self.capture()
            current_y = grub_editor_left_cursor_y(frame)
            if current_y is not None and current_y >= previous_y + 8:
                self.current_frame = frame
                self._editor_cursor_y = current_y
                return
            time.sleep(0.05)
        raise ProtocolError("GRUB editor cursor did not move to the next line")

    def move_editor_cursor_to_end(self) -> None:
        """Wait until GRUB has applied End to the selected linux line."""

        if self.current_frame is None or self._editor_cursor_y is None:
            raise ProtocolError("GRUB editor cursor is not synchronized")
        before = self.current_frame
        self.qmp.send_key("end")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            frame = self.capture()
            if (
                grub_editor_layout(frame) is not None
                and grub_editor_left_cursor_y(frame) is None
                and grub_frame_difference(before, frame) >= 8
            ):
                self.current_frame = frame
                self._editor_cursor_y = None
                return
            time.sleep(0.05)
        raise ProtocolError("GRUB editor cursor did not move to the line end")

    def type_text_verified(self, value: str) -> None:
        """Inject editor text one character at a time with framebuffer ACKs."""

        if self.current_frame is None or not value:
            raise ProtocolError("GRUB editor is not ready for verified text input")
        for index, character in enumerate(value):
            before = self.current_frame
            self.qmp.type_text(character, interval=0)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                frame = self.capture()
                if (
                    grub_editor_layout(frame) is not None
                    and grub_frame_difference(before, frame) >= 2
                ):
                    self.current_frame = frame
                    break
                time.sleep(0.03)
            else:
                raise ProtocolError(
                    "GRUB did not paint verified text character "
                    f"{index + 1}/{len(value)}"
                )

    def wait_for_change(
        self,
        before: Path,
        *,
        timeout: float,
        minimum_change: int,
    ) -> Path:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self.capture()
            if grub_frame_difference(before, frame) >= minimum_change:
                self.current_frame = frame
                return frame
            time.sleep(0.1)
        raise ProtocolError("GRUB framebuffer did not reflect the requested action")
