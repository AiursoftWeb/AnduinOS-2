"""Deterministic visual assertions over QEMU screendumps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .errors import TestFailure


@dataclass(frozen=True)
class GrubMenuLayout:
    """Resolution-independent geometry of one painted GRUB menu."""

    top: int
    bottom: int
    highlight_center: int
    visible_unselected_entries: int


@dataclass(frozen=True)
class GrubEditorLayout:
    """Geometry and command content of a painted GRUB entry editor."""

    top: int
    bottom: int
    visible_command_lines: int


def grub_frame_difference(first: Path, second: Path) -> int:
    """Count changed foreground pixels while ignoring color-only firmware noise."""

    before_width, before_height, before = _read_ppm_grayscale(first)
    after_width, after_height, after = _read_ppm_grayscale(second)
    if (before_width, before_height) != (after_width, after_height):
        return before_width * before_height
    first_mask = bytes(value >= 96 for value in before)
    second_mask = bytes(value >= 96 for value in after)
    return sum(left != right for left, right in zip(first_mask, second_mask, strict=True))


def grub_menu_layout(frame: Path) -> GrubMenuLayout | None:
    """Return semantic menu geometry; editor and firmware frames return None."""

    width, height, grayscale = _read_ppm_grayscale(frame)
    if width < 320 or height < 200:
        return None
    if sum(value <= 48 for value in grayscale) < width * height * 3 // 4:
        return None
    wide_rows: list[int] = []
    # The signed amd64 GRUB path uses the stock text layout, whose lower menu
    # border is painted at roughly 84% of the framebuffer.  Scanning only the
    # first four fifths silently discarded that border and made a real Secure
    # Boot menu indistinguishable from an editor/firmware frame.  Leave the
    # bottom eighth for GRUB's help text while including both supported menu
    # layouts.
    for y in range(height * 7 // 8):
        row = grayscale[y * width : (y + 1) * width]
        if sum(96 <= value <= 240 for value in row) >= width * 7 // 10:
            wide_rows.append(y)
    wide_bands = _integer_bands(wide_rows, maximum_gap=0)
    if len(wide_bands) < 3:
        return None
    top = wide_bands[0][0]
    bottom = wide_bands[-1][1]
    interior = wide_bands[1:-1]
    highlight = max(interior, key=lambda band: band[1] - band[0])
    if highlight[1] - highlight[0] + 1 < 8 or bottom - top < height // 4:
        return None

    active_rows: list[int] = []
    # Stay comfortably inside the vertical border; its two antialiased pixels
    # otherwise make every interior scanline look like one giant text band.
    left = width // 20
    right = width - left
    for y in range(top + 4, bottom - 3):
        if highlight[0] <= y <= highlight[1]:
            continue
        row = grayscale[y * width + left : y * width + right]
        if sum(value >= 96 for value in row) >= max(3, width // 1000):
            active_rows.append(y)
    entry_bands = _integer_bands(active_rows, maximum_gap=2)
    return GrubMenuLayout(
        top=top,
        bottom=bottom,
        highlight_center=(highlight[0] + highlight[1]) // 2,
        visible_unselected_entries=len(entry_bands),
    )


def grub_editor_layout(frame: Path) -> GrubEditorLayout | None:
    """Return a semantic editor layout; blank, menu, and boot frames fail."""

    width, height, grayscale = _read_ppm_grayscale(frame)
    wide_rows = [
        y
        for y in range(height * 7 // 8)
        if sum(
            96 <= value <= 240
            for value in grayscale[y * width : (y + 1) * width]
        )
        >= width * 7 // 10
    ]
    border_bands = _integer_bands(wide_rows, maximum_gap=0)
    if len(border_bands) != 2:
        return None
    top = border_bands[0][0]
    bottom = border_bands[1][1]
    if bottom - top < height // 4:
        return None
    active_rows: list[int] = []
    # Stay comfortably inside both vertical borders.  The first command starts
    # at a fixed x~=14 in stock GRUB but extends far past this inset, while the
    # remaining linux/initrd lines are already indented.
    left = width // 20
    right = width - left
    for y in range(top + 4, bottom - 4):
        row = grayscale[y * width + left : y * width + right]
        if sum(value >= 96 for value in row) >= max(3, width // 1000):
            active_rows.append(y)
    command_bands = _integer_bands(active_rows, maximum_gap=2)
    # Supported locale entries contain setparams, gfxpayload, linux and initrd.
    # A partially repainted 28-entry locale menu can temporarily lose its wide
    # highlight band; rejecting crowded content prevents that transient menu
    # from masquerading as the editor after the `e` key.
    # While a long linux line is wrapping, the first few glyphs on its new
    # visual row can form several disconnected horizontal bands. The Live
    # keyboard argument made one real trace briefly reach nine bands while
    # typing k=s; the 28-entry locale menu remains far above this bound.
    if not 3 <= len(command_bands) <= 12:
        return None
    return GrubEditorLayout(
        top=top,
        bottom=bottom,
        visible_command_lines=len(command_bands),
    )


def grub_editor_left_cursor_y(frame: Path) -> int | None:
    """Locate stock GRUB's small underline cursor in the left command column."""

    layout = grub_editor_layout(frame)
    if layout is None:
        return None
    width, _height, grayscale = _read_ppm_grayscale(frame)
    minimum_width = max(6, width // 240)
    maximum_width = max(24, width // 40)
    candidates: list[tuple[int, int, int]] = []
    for y in range(layout.top + 4, layout.bottom - 4):
        row = grayscale[y * width : (y + 1) * width]
        start: int | None = None
        for x in range(width // 16):
            painted = row[x] >= 96
            if painted and start is None:
                start = x
            elif not painted and start is not None:
                run_width = x - start
                if minimum_width <= run_width <= maximum_width:
                    candidates.append((start, x - 1, y))
                start = None
    groups: dict[tuple[int, int], list[int]] = {}
    for left, right, y in candidates:
        if left <= width // 35:
            groups.setdefault((left, right), []).append(y)
    candidates: list[tuple[int, int, int]] = []
    for (left, right), rows in groups.items():
        bands = [
            (top, bottom)
            for top, bottom in _integer_bands(rows, maximum_gap=0)
            if 2 <= bottom - top + 1 <= 4
        ]
        # Horizontal strokes in the first command's glyphs recur at multiple
        # heights with the same x-range.  GRUB's underline cursor is one
        # unique solid band and is wider than those nearby glyph strokes.
        if len(bands) == 1:
            top, bottom = bands[0]
            candidates.append((right - left + 1, -left, (top + bottom) // 2))
    if candidates:
        best = max(candidates)
        competing_widths = [width for width, left, _y in candidates if (width, left) != best[:2]]
        if not competing_widths or best[0] >= max(competing_widths) + 2:
            return best[2]
    return None


def _integer_bands(values: list[int], *, maximum_gap: int) -> list[tuple[int, int]]:
    bands: list[list[int]] = []
    for value in values:
        if not bands or value - bands[-1][-1] > maximum_gap + 1:
            bands.append([])
        bands[-1].append(value)
    return [(band[0], band[-1]) for band in bands]


def _read_ppm_grayscale(path: Path) -> tuple[int, int, bytes]:
    """Read QEMU's P6 screendump without invoking an image-codec extension."""

    try:
        with path.open("rb") as stream:
            def token() -> bytes:
                while True:
                    value = stream.read(1)
                    if not value:
                        raise TestFailure(f"Truncated PPM header: {path.name}")
                    if value == b"#":
                        stream.readline()
                        continue
                    if not value.isspace():
                        break
                result = bytearray(value)
                while True:
                    value = stream.read(1)
                    if not value or value.isspace():
                        return bytes(result)
                    result.extend(value)
                    if len(result) > 32:
                        raise TestFailure(
                            f"Unsafe PPM header token in {path.name}"
                        )

            magic = token()
            width_token = token()
            height_token = token()
            maximum_token = token()
            if magic != b"P6" or maximum_token != b"255":
                raise TestFailure(f"Unsupported PPM screendump: {path.name}")
            try:
                width = int(width_token)
                height = int(height_token)
            except ValueError as error:
                raise TestFailure(f"Invalid PPM dimensions: {path.name}") from error
            if (
                not 1 <= width <= 16384
                or not 1 <= height <= 16384
                or width * height > 64 * 1024 * 1024
            ):
                raise TestFailure(f"Unsafe PPM dimensions: {width}x{height}")
            expected = width * height * 3
            rgb = stream.read(expected + 1)
    except OSError as error:
        raise TestFailure(f"Cannot read PPM screendump {path.name}: {error}") from error
    if len(rgb) != expected:
        raise TestFailure(
            f"Incomplete PPM screendump {path.name}: {len(rgb)}/{expected} RGB bytes"
        )
    return width, height, rgb[0::3]


def assert_font_fixture(screenshot: Path, report: Path) -> None:
    """Reject monochrome/tofu rendering of the acceptance font fixture."""

    with Image.open(screenshot) as source:
        image = source.convert("RGB")
    width, height = image.size
    pixels = _pixels(image)
    green = sum(
        1
        for red, value, blue in pixels
        if value >= 90 and value >= red + 25 and value >= blue + 10
    )
    white = sum(1 for red, value, blue in pixels if min(red, value, blue) >= 235)
    lower = image.crop((0, height // 2, width, height))
    lower_dark = sum(
        1
        for red, value, blue in _pixels(lower)
        if max(red, value, blue) <= 100
    )
    values = {
        "width": width,
        "height": height,
        "green_pixels": green,
        "white_pixels": white,
        "lower_half_dark_pixels": lower_dark,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    minimum_area = max(100, width * height // 5000)
    if green < minimum_area:
        raise TestFailure(
            "The rendered pistol is not green; Twemoji color rendering was not observed "
            f"({green} green pixels, expected at least {minimum_area})"
        )
    if white < width * height // 2:
        raise TestFailure("The deterministic full-screen font fixture was not visible")
    if lower_dark < minimum_area:
        raise TestFailure("The Chinese acceptance phrase produced no visible glyphs")


def assert_pointer_motion(before: Path, after: Path, report: Path) -> None:
    """Prove that GDM painted a movable cursor at two requested positions."""

    with Image.open(before) as source:
        first = source.convert("RGB")
    with Image.open(after) as source:
        second = source.convert("RGB")
    if first.size != second.size:
        raise TestFailure("GDM pointer frames have different dimensions")
    width, height = first.size
    first_pixels = first.load()
    second_pixels = second.load()
    changed: list[tuple[int, int]] = []
    for y in range(int(height * 0.25), int(height * 0.75)):
        for x in range(width):
            if max(
                abs(first_pixels[x, y][channel] - second_pixels[x, y][channel])
                for channel in range(3)
            ) >= 30:
                changed.append((x, y))
    left = sum(
        1
        for x, y in changed
        if width * 0.12 <= x <= width * 0.38
        and height * 0.32 <= y <= height * 0.68
    )
    right = sum(
        1
        for x, y in changed
        if width * 0.62 <= x <= width * 0.88
        and height * 0.32 <= y <= height * 0.68
    )
    values = {
        "screen_size": [width, height],
        "changed_pixels": len(changed),
        "left_target_changed_pixels": left,
        "right_target_changed_pixels": right,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    if left < 12 or right < 12:
        raise TestFailure(
            "Moving the absolute pointer did not repaint a cursor at both GDM "
            f"target positions (left={left}, right={right})"
        )
    if len(changed) > width * height // 25:
        raise TestFailure(
            "GDM pointer frames changed too broadly for a cursor-only oracle "
            f"({len(changed)} pixels)"
        )


def assert_start_button_logo(
    frame: Path,
    template: Path,
    bounds: list[object],
    report: Path,
) -> None:
    """Match the rendered Start button to the installed AnduinOS SVG template."""

    _assert_anduinos_logo(
        frame,
        template,
        bounds,
        report,
        context="Start button",
        allow_bottom_panel_fallback=True,
    )


def assert_settings_about_logo(
    frame: Path,
    templates: list[Path],
    bounds: list[object],
    report: Path,
) -> None:
    """Match Settings' visible system logo to one shipped light/dark asset."""

    if len(templates) != 2 or len(set(templates)) != 2:
        raise TestFailure(
            "GNOME Settings did not return both installed About logo variants"
        )
    attempts: list[dict[str, str]] = []
    for index, template in enumerate(templates):
        attempt_report = report.with_name(f"{report.stem}-{index}{report.suffix}")
        try:
            _assert_anduinos_logo(
                frame,
                template,
                bounds,
                attempt_report,
                context="GNOME Settings About logo",
                allow_bottom_panel_fallback=False,
                search_entire_frame=True,
            )
        except TestFailure as error:
            attempts.append({"template": str(template), "error": str(error)})
            continue
        report.write_text(
            json.dumps(
                {
                    "matched_template": str(template),
                    "analysis": str(attempt_report),
                    "failed_variants": attempts,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    report.write_text(
        json.dumps({"failed_variants": attempts}, indent=2) + "\n",
        encoding="utf-8",
    )
    raise TestFailure(
        "The visible GNOME Settings About logo matched neither installed "
        f"AnduinOS asset: {attempts}"
    )


def assert_swapcontrol_green(frame: Path, report: Path) -> None:
    """Require Swap Control's dashboard to paint a substantial green region."""

    with Image.open(frame) as source:
        image = source.convert("RGB")
    width, height = image.size
    green_points = []
    for y in range(height):
        for x in range(width):
            red, green, blue = image.getpixel((x, y))
            if green >= 90 and green >= red + 24 and green >= blue + 8:
                green_points.append((x, y))
    if green_points:
        xs = [point[0] for point in green_points]
        ys = [point[1] for point in green_points]
        bounds = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
    else:
        bounds = [0, 0, 0, 0]
    values = {
        "screen_size": [width, height],
        "green_pixels": len(green_points),
        "green_fraction": round(len(green_points) / (width * height), 5),
        "green_bounds": bounds,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    green_width = bounds[2] - bounds[0]
    green_height = bounds[3] - bounds[1]
    if len(green_points) < max(500, width * height // 2000):
        raise TestFailure(
            "Swap Control did not paint enough of its green dashboard state: "
            f"{values}"
        )
    if green_width < 60 or green_height < 60:
        raise TestFailure(
            "Swap Control green pixels did not form a substantial UI region: "
            f"{values}"
        )


def assert_cpu_z_thumbnail(frame: Path, report: Path) -> None:
    """Require CPU-Z's embedded white-chip-on-purple icon, not a generic icon."""

    try:
        with Image.open(frame) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as error:
        raise TestFailure(f"CPU-Z thumbnail is not a readable image: {error}")
    width, height = image.size
    pixels = _pixels(image)
    white = sum(1 for red, green, blue in pixels if min(red, green, blue) >= 235)
    purple = sum(
        1
        for red, green, blue in pixels
        if blue >= 75 and blue >= red + 35 and blue >= green + 55
    )
    center = image.getpixel((width // 2, height // 2))
    corners = (
        image.getpixel((0, 0)),
        image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)),
        image.getpixel((width - 1, height - 1)),
    )
    values = {
        "image_size": [width, height],
        "white_pixels": white,
        "purple_pixels": purple,
        "center_rgb": list(center),
        "corner_rgb": [list(value) for value in corners],
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    area = width * height
    if width < 128 or height < 128 or width != height:
        raise TestFailure(f"CPU-Z thumbnail has an implausible size: {width}x{height}")
    if white < area // 8 or purple < area // 2:
        raise TestFailure(
            "CPU-Z thumbnail does not contain its embedded white/purple artwork: "
            f"{values}"
        )
    if min(center) < 235:
        raise TestFailure("CPU-Z thumbnail lost the white center of its chip icon")
    if any(
        not (blue >= 75 and blue >= red + 35 and blue >= green + 55)
        for red, green, blue in corners
    ):
        raise TestFailure("CPU-Z thumbnail lost its purple corner background")


def assert_wechat_login_window(
    frame: Path,
    report: Path,
    evidence: object,
) -> None:
    """Require WeChat's mapped X11 window to visibly contain its QR login UI."""

    if not isinstance(evidence, dict):
        raise TestFailure("WeChat visual evidence is not an object")
    window = evidence.get("main_window")
    if not isinstance(window, dict):
        raise TestFailure("WeChat visual evidence has no main X11 window")
    try:
        left = int(window["x"])
        top = int(window["y"])
        width = int(window["width"])
        height = int(window["height"])
    except (KeyError, TypeError, ValueError) as error:
        raise TestFailure("WeChat returned malformed X11 window geometry") from error
    try:
        with Image.open(frame) as source:
            screen = source.convert("RGB")
    except (OSError, ValueError) as error:
        raise TestFailure(f"WeChat screenshot is unreadable: {error}") from error
    screen_width, screen_height = screen.size
    if (
        width < 200
        or height < 250
        or left < 0
        or top < 0
        or left + width > screen_width
        or top + height > screen_height
    ):
        raise TestFailure(
            f"WeChat returned unusable visible window geometry: {[left, top, width, height]}"
        )
    crop = screen.crop((left, top, left + width, top + height))
    qr = crop.crop(
        (
            round(width * 0.15),
            round(height * 0.10),
            round(width * 0.85),
            round(height * 0.62),
        )
    )
    qr_pixels = _pixels(qr)
    crop_pixels = _pixels(crop)
    dark = sum(max(pixel) < 70 for pixel in qr_pixels)
    light = sum(min(pixel) > 215 for pixel in qr_pixels)
    green = sum(
        green >= 130 and green >= red + 50 and green >= blue + 35
        for red, green, blue in crop_pixels
    )
    bright = sum(min(pixel) > 205 for pixel in crop_pixels)
    binary = [max(pixel) < 100 for pixel in qr_pixels]
    qr_width, qr_height = qr.size
    horizontal_transitions = sum(
        binary[row * qr_width + column]
        != binary[row * qr_width + column - 1]
        for row in range(qr_height)
        for column in range(1, qr_width)
    )
    vertical_transitions = sum(
        binary[row * qr_width + column]
        != binary[(row - 1) * qr_width + column]
        for row in range(1, qr_height)
        for column in range(qr_width)
    )
    values = {
        "screen_size": [screen_width, screen_height],
        "window": window,
        "crop_size": [width, height],
        "qr_region_size": [qr_width, qr_height],
        "qr_dark_pixels": dark,
        "qr_light_pixels": light,
        "qr_horizontal_transitions": horizontal_transitions,
        "qr_vertical_transitions": vertical_transitions,
        "green_pixels": green,
        "bright_window_pixels": bright,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    qr_area = max(1, qr_width * qr_height)
    window_area = width * height
    if (
        dark < qr_area * 0.05
        or light < qr_area * 0.40
        or horizontal_transitions < 500
        or vertical_transitions < 500
        or green < 50
        or bright < window_area * 0.50
    ):
        raise TestFailure(
            "The mapped WeChat window does not visibly contain its QR login UI"
        )


def assert_fixture_quadrants(frame: Path, report: Path) -> None:
    """Require the project-owned red/green/blue/yellow fixture composition."""

    try:
        with Image.open(frame) as source:
            image = source.convert("RGB")
    except (OSError, ValueError) as error:
        raise TestFailure(f"Fixture visual evidence is not a readable image: {error}")
    width, height = image.size
    points: dict[str, list[tuple[int, int]]] = {
        "red": [],
        "green": [],
        "blue": [],
        "yellow": [],
    }
    for y in range(height):
        for x in range(width):
            red, green, blue = image.getpixel((x, y))
            if red >= 150 and red >= green + 60 and red >= blue + 40:
                points["red"].append((x, y))
            elif green >= 130 and green >= red + 50 and green >= blue + 20:
                points["green"].append((x, y))
            elif blue >= 150 and blue >= red + 50 and blue >= green + 40:
                points["blue"].append((x, y))
            elif red >= 150 and green >= 130 and blue <= 110:
                points["yellow"].append((x, y))
    minimum = max(200, width * height // 500)
    counts = {name: len(values) for name, values in points.items()}
    centroids = {
        name: [
            round(sum(x for x, _y in values) / len(values), 2),
            round(sum(y for _x, y in values) / len(values), 2),
        ]
        for name, values in points.items()
        if values
    }
    stable_colors = ("red", "green", "yellow")
    if any(counts[name] < minimum for name in stable_colors):
        values = {
            "image_size": [width, height],
            "minimum_pixels_per_color": minimum,
            "color_pixels": counts,
            "centroids": centroids,
        }
        report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
        raise TestFailure(
            "The visible file fixture lost one or more content quadrants: "
            f"{counts}"
        )
    red_center = centroids["red"]
    green_center = centroids["green"]
    yellow_center = centroids["yellow"]
    horizontal = green_center[0] - red_center[0]
    vertical = yellow_center[1] - green_center[1]
    expected_blue = (red_center[0], yellow_center[1])
    blue_region = [
        point
        for point in points["blue"]
        if abs(point[0] - expected_blue[0]) <= max(30, horizontal * 0.65)
        and abs(point[1] - expected_blue[1]) <= max(30, vertical * 0.65)
    ]
    blue_local_center = (
        [
            round(sum(x for x, _y in blue_region) / len(blue_region), 2),
            round(sum(y for _x, y in blue_region) / len(blue_region), 2),
        ]
        if blue_region
        else []
    )
    values = {
        "image_size": [width, height],
        "minimum_pixels_per_color": minimum,
        "color_pixels": counts,
        "centroids": centroids,
        "expected_blue_centroid": [round(value, 2) for value in expected_blue],
        "local_blue_pixels": len(blue_region),
        "local_blue_centroid": blue_local_center,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    if len(blue_region) < minimum:
        raise TestFailure(
            "The visible file fixture lost one or more content quadrants: "
            f"global={counts}, local_blue={len(blue_region)}"
        )
    blue_center = blue_local_center
    if not (
        horizontal > 30
        and vertical > 30
        and red_center[0] < green_center[0]
        and blue_center[0] < yellow_center[0]
        and red_center[1] < blue_center[1]
        and green_center[1] < yellow_center[1]
        and abs(red_center[1] - green_center[1]) <= vertical * 0.4 + 12
        and abs(green_center[0] - yellow_center[0]) <= horizontal * 0.4 + 12
        and abs(red_center[0] - blue_center[0]) <= horizontal * 0.4 + 12
        and abs(blue_center[1] - yellow_center[1]) <= vertical * 0.4 + 12
    ):
        raise TestFailure(
            "The visible file fixture colors do not retain their 2x2 layout: "
            f"{centroids}"
        )


def _assert_anduinos_logo(
    frame: Path,
    template: Path,
    bounds: list[object],
    report: Path,
    *,
    context: str,
    allow_bottom_panel_fallback: bool,
    search_entire_frame: bool = False,
) -> None:
    """Locate a rendered AnduinOS wordmark using semantic screen bounds."""

    if (
        len(bounds) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bounds)
    ):
        raise TestFailure(f"The {context} returned malformed AT-SPI bounds")
    raw_bounds = [round(float(value)) for value in bounds]
    left, top, width, height = raw_bounds
    with Image.open(frame) as source:
        screen = source.convert("RGB")
    with Image.open(template) as source:
        logo = source.convert("RGBA")
    screen_width, screen_height = screen.size
    logo_width, logo_height = logo.size
    semantic_size_usable = width >= logo_width and height >= logo_height
    semantic_bounds_usable = semantic_size_usable and not (
        left < 0
        or top < 0
        or height < logo_height
        or left + width > screen_width
        or top + height > screen_height
    )
    if search_entire_frame:
        if not semantic_size_usable:
            raise TestFailure(
                f"The {context} returned unusable AT-SPI dimensions: {raw_bounds}"
            )
        # GTK4 on Wayland exposes reliable control dimensions and WINDOW
        # coordinates, but deliberately reports (0, 0) for SCREEN coordinates.
        # Search the captured frame for the exact rendered asset instead of
        # pretending that an application-relative origin is global.
        left = 0
        top = 0
        width = screen_width
        height = screen_height
    elif not semantic_bounds_usable and allow_bottom_panel_fallback:
        # GNOME Shell 50 exposes the exact named Start toggle but may publish
        # a zero-sized component rectangle for panel actors.  Fall back to a
        # normalized bottom-panel search, then let the installed SVG's shape
        # and colors determine the exact location.  No absolute screen pixel
        # or product-specific taskbar coordinate is assumed.
        left = 0
        top = round(screen_height * 0.7)
        width = screen_width
        height = screen_height - top
    elif not semantic_bounds_usable:
        raise TestFailure(
            f"The {context} returned unusable AT-SPI bounds: {raw_bounds}"
        )

    logo_pixels = logo.load()
    opaque = [
        (x, y, logo_pixels[x, y][:3])
        for y in range(logo_height)
        for x in range(logo_width)
        if logo_pixels[x, y][3] >= 160
    ]
    # Match the blue layered mark independently from the black/white wordmark.
    # The latter changes with the light/dark asset while the mark remains a
    # stable product identity and gives a reliable foreground mask.
    mask = {
        (x, y)
        for y in range(logo_height)
        for x in range(logo_width)
        if logo_pixels[x, y][3] >= 64
        and logo_pixels[x, y][2] >= 120
        and logo_pixels[x, y][2] >= logo_pixels[x, y][0] + 35
        and logo_pixels[x, y][2] >= logo_pixels[x, y][1] + 20
    }
    if len(opaque) < 32 or len(mask) < 32:
        raise TestFailure(
            f"The installed {context} template has too little AnduinOS content"
        )
    if len(opaque) > 500:
        stride = max(1, len(opaque) // 500)
        opaque = opaque[::stride][:500]

    screen_pixels = screen.load()
    best = {
        "mask_iou": 0.0,
        "color_inlier_fraction": 0.0,
        "mean_rgb_error": 765.0,
        "position": [left, top],
    }
    anchor_x, anchor_y = min(
        mask,
        key=lambda point: abs(point[0] - logo_width / 2)
        + abs(point[1] - logo_height / 2),
    )
    candidate_positions = set()
    for actual_y in range(top, top + height):
        for actual_x in range(left, left + width):
            red, green, blue = screen_pixels[actual_x, actual_y]
            if blue < 120 or blue < red + 35 or blue < green + 20:
                continue
            candidate_x = actual_x - anchor_x
            candidate_y = actual_y - anchor_y
            if (
                left <= candidate_x <= left + width - logo_width
                and top <= candidate_y <= top + height - logo_height
            ):
                candidate_positions.add((candidate_x, candidate_y))
    if not candidate_positions:
        raise TestFailure(
            f"The {context} search region contains no AnduinOS-blue pixels"
        )
    # A full Wayland frame can contain a blue wallpaper, so do not run the
    # expensive mask oracle for every blue pixel. Rank candidates first using
    # sparse samples from both the layered mark and the ANDUINOS wordmark.
    probe_stride = max(1, len(opaque) // 32)
    probes = opaque[::probe_stride][:32]
    ranked_candidates = []
    for candidate_x, candidate_y in candidate_positions:
        errors = []
        for x, y, expected in probes:
            actual = screen_pixels[candidate_x + x, candidate_y + y]
            errors.append(
                sum(
                    abs(actual[channel] - expected[channel])
                    for channel in range(3)
                )
            )
        inlier_fraction = sum(error <= 105 for error in errors) / len(errors)
        mean_error = sum(errors) / len(errors)
        if inlier_fraction >= 0.2 and mean_error <= 300:
            ranked_candidates.append(
                (inlier_fraction, -mean_error, candidate_x, candidate_y)
            )
    ranked_candidates.sort(reverse=True)
    ranked_candidates = ranked_candidates[:128]
    for _probe_inliers, _probe_error, candidate_x, candidate_y in ranked_candidates:
        actual_mask = set()
        for y in range(logo_height):
            for x in range(logo_width):
                red, green, blue = screen_pixels[candidate_x + x, candidate_y + y]
                if blue >= 120 and blue >= red + 35 and blue >= green + 20:
                    actual_mask.add((x, y))
        union = mask | actual_mask
        iou = len(mask & actual_mask) / len(union) if union else 0.0
        total_error = 0
        inliers = 0
        for x, y, expected in opaque:
            actual = screen_pixels[candidate_x + x, candidate_y + y]
            error = sum(
                abs(actual[channel] - expected[channel]) for channel in range(3)
            )
            total_error += error
            if error <= 105:
                inliers += 1
        inlier_fraction = inliers / len(opaque)
        mean_error = total_error / len(opaque)
        score = (iou, inlier_fraction, -mean_error)
        current = (
            best["mask_iou"],
            best["color_inlier_fraction"],
            -best["mean_rgb_error"],
        )
        if score > current:
            best = {
                "mask_iou": round(iou, 4),
                "color_inlier_fraction": round(inlier_fraction, 4),
                "mean_rgb_error": round(mean_error, 2),
                "position": [candidate_x, candidate_y],
            }
    values = {
        "screen_size": [screen_width, screen_height],
        "atspi_bounds": raw_bounds,
        "semantic_bounds_usable": semantic_bounds_usable,
        "search_bounds": [left, top, width, height],
        "template_size": [logo_width, logo_height],
        "template_mask_pixels": len(mask),
        "blue_anchor_candidates": len(candidate_positions),
        "ranked_candidates": len(ranked_candidates),
        **best,
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    if (
        best["mask_iou"] < 0.55
        or best["color_inlier_fraction"] < 0.55
        or best["mean_rgb_error"] > 145
    ):
        raise TestFailure(
            f"The visible {context} did not match the installed AnduinOS logo: "
            f"{best}"
        )


def assert_theme_transition(light: Path, dark: Path, report: Path) -> None:
    """Require a centered application surface to visibly change light to dark."""

    with Image.open(light) as source:
        light_image = source.convert("RGB")
    with Image.open(dark) as source:
        dark_image = source.convert("RGB")
    if light_image.size != dark_image.size:
        raise TestFailure("Theme fixture frames have different dimensions")
    width, height = light_image.size
    # Each fixture is maximized or compositor-centered. Staying well inside
    # the center avoids wallpaper, the taskbar, title-bar controls, and shadows.
    bounds = (
        int(width * 0.32),
        int(height * 0.32),
        int(width * 0.68),
        int(height * 0.68),
    )
    light_region = light_image.crop(bounds)
    dark_region = dark_image.crop(bounds)
    light_luma = [_luminance(pixel) for pixel in _pixels(light_region)]
    dark_luma = [_luminance(pixel) for pixel in _pixels(dark_region)]
    light_median = _median(light_luma)
    dark_median = _median(dark_luma)
    bright_fraction = sum(value >= 170 for value in light_luma) / len(light_luma)
    dark_fraction = sum(value <= 100 for value in dark_luma) / len(dark_luma)
    values = {
        "screen_size": [width, height],
        "normalized_region": [0.32, 0.32, 0.68, 0.68],
        "light_median_luminance": round(light_median, 2),
        "dark_median_luminance": round(dark_median, 2),
        "light_bright_fraction": round(bright_fraction, 4),
        "dark_dark_fraction": round(dark_fraction, 4),
        "median_delta": round(light_median - dark_median, 2),
    }
    report.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    if bright_fraction < 0.55:
        raise TestFailure(
            "The fixture's light frame did not paint a predominantly light "
            f"application surface ({bright_fraction:.3f})"
        )
    if dark_fraction < 0.55:
        raise TestFailure(
            "The fixture's dark frame did not paint a predominantly dark "
            f"application surface ({dark_fraction:.3f})"
        )
    if light_median - dark_median < 70:
        raise TestFailure(
            "The same application surface did not visibly transition from "
            f"light to dark (median delta {light_median - dark_median:.1f})"
        )


def _pixels(image: Image.Image):
    modern = getattr(image, "get_flattened_data", None)
    return modern() if modern is not None else image.getdata()


def _luminance(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def plymouth_match(frame: Path, watermark: Path) -> dict[str, object]:
    """Match the unscaled AnduinOS watermark near Plymouth's bottom center."""

    with Image.open(frame) as source:
        screen = source.convert("RGB")
    with Image.open(watermark) as source:
        logo = source.convert("RGBA")
    width, height = screen.size
    logo_width, logo_height = logo.size
    if logo_width > width or logo_height > height:
        return {"matched": False, "reason": "watermark larger than screen"}

    # Fully opaque samples are stable across firmware backgrounds and avoid
    # having to guess the RGB value under antialiased transparent edge pixels.
    candidates = [
        (x, y, logo.getpixel((x, y))[:3])
        for y in range(0, logo_height, 3)
        for x in range(0, logo_width, 3)
        if logo.getpixel((x, y))[3] >= 250
    ]
    if len(candidates) > 240:
        stride = max(1, len(candidates) // 240)
        candidates = candidates[::stride][:240]
    if not candidates:
        return {"matched": False, "reason": "watermark has no opaque samples"}

    center = (width - logo_width) // 2
    x_min = max(0, center - 24)
    x_max = min(width - logo_width, center + 24)
    y_min = max(0, int(height * 0.68) - logo_height)
    y_max = height - logo_height
    best_fraction = 0.0
    best_mean_error = 765.0
    best_position = (center, y_max)
    screen_pixels = screen.load()
    for top in range(y_min, y_max + 1):
        for left in range(x_min, x_max + 1, 2):
            inliers = 0
            total_error = 0
            for offset_x, offset_y, expected in candidates:
                actual = screen_pixels[left + offset_x, top + offset_y]
                error = sum(abs(actual[index] - expected[index]) for index in range(3))
                total_error += error
                if error <= 75:
                    inliers += 1
            fraction = inliers / len(candidates)
            mean_error = total_error / len(candidates)
            if (fraction, -mean_error) > (best_fraction, -best_mean_error):
                best_fraction = fraction
                best_mean_error = mean_error
                best_position = (left, top)
    return {
        "matched": best_fraction >= 0.72 and best_mean_error <= 95,
        "fraction": round(best_fraction, 4),
        "mean_rgb_error": round(best_mean_error, 2),
        "position": list(best_position),
        "screen_size": [width, height],
        "watermark_size": [logo_width, logo_height],
        "samples": len(candidates),
    }
