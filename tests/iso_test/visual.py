"""Deterministic visual assertions over QEMU screendumps."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .errors import TestFailure


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


def _pixels(image: Image.Image):
    modern = getattr(image, "get_flattened_data", None)
    return modern() if modern is not None else image.getdata()


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
