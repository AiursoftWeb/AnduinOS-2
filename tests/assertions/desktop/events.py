"""Shared parsing helpers for JSON events emitted by guest UI drivers."""

import json

from framework.errors import TestFailure


def _event_objects(output: str, kind: str) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == kind:
            values.append(value)
    return values


def _all_event_objects(output: str) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            values.append(value)
    return values


def _one_event(
    events: list[dict[str, object]],
    *,
    context: str,
    **required: object,
) -> tuple[int, dict[str, object]]:
    matches = [
        (index, value)
        for index, value in enumerate(events)
        if all(value.get(key) == expected for key, expected in required.items())
    ]
    if len(matches) != 1:
        detail = ", ".join(f"{key}={value!r}" for key, value in required.items())
        raise TestFailure(
            f"{context} requires exactly one semantic event ({detail}); "
            f"observed {len(matches)}"
        )
    return matches[0]


__all__ = tuple(name for name in globals() if name.startswith("_"))
