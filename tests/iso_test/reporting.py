"""Machine-readable reports derived from the acceptance dashboard state."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def write_junit_report(summary: dict[str, object], destination: Path) -> None:
    """Write fail-closed JUnit XML for every parent and declared child check."""

    suites: list[ET.Element] = []
    for record in summary.get("results", []):
        suites.append(_suite_element("installation", record))
    for record in summary.get("feature_suites", []):
        suites.append(_suite_element("feature", record))

    totals = _totals(suites)
    root = ET.Element(
        "testsuites",
        {
            "name": "AnduinOS ISO Acceptance",
            "tests": str(totals[0]),
            "failures": str(totals[1]),
            "errors": str(totals[2]),
            "time": _seconds(sum(_float(item.get("time")) for item in suites)),
        },
    )
    for suite in suites:
        root.append(suite)
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    temporary = destination.with_name(f".{destination.name}.tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(destination)


def _suite_element(kind: str, record: object) -> ET.Element:
    if not isinstance(record, dict):
        raise TypeError("Acceptance summary records must be objects")
    identifier = str(record.get("id", "unknown"))
    children = record.get("checks", [])
    if not isinstance(children, list):
        raise TypeError(f"{identifier}: checks must be a list")
    cases = [
        _testcase(
            classname=f"{kind}.{identifier}",
            name=f"{kind}-result",
            status=str(record.get("status", "pending")),
            seconds=record.get("seconds"),
            detail=str(record.get("error") or record.get("detail") or ""),
        )
    ]
    for child in children:
        if not isinstance(child, dict):
            raise TypeError(f"{identifier}: check records must be objects")
        cases.append(
            _testcase(
                classname=f"{kind}.{identifier}",
                name=str(child.get("id", "unknown-check")),
                status=str(child.get("status", "pending")),
                seconds=child.get("seconds"),
                detail=str(child.get("detail") or ""),
            )
        )
    failures = sum(item.find("failure") is not None for item in cases)
    errors = sum(item.find("error") is not None for item in cases)
    suite = ET.Element(
        "testsuite",
        {
            "name": f"{kind}:{identifier}",
            "tests": str(len(cases)),
            "failures": str(failures),
            "errors": str(errors),
            "time": _seconds(record.get("seconds")),
        },
    )
    for case in cases:
        suite.append(case)
    return suite


def _testcase(
    *,
    classname: str,
    name: str,
    status: str,
    seconds: object,
    detail: str,
) -> ET.Element:
    case = ET.Element(
        "testcase",
        {
            "classname": classname,
            "name": name,
            "time": _seconds(seconds),
        },
    )
    if status == "failed":
        failure = ET.SubElement(
            case,
            "failure",
            {"type": "AcceptanceFailure", "message": detail or "Test failed"},
        )
        failure.text = detail or "Test failed"
    elif status != "passed":
        error = ET.SubElement(
            case,
            "error",
            {
                "type": "IncompleteAcceptanceCheck",
                "message": detail or f"Check ended in state {status}",
            },
        )
        error.text = detail or f"Check ended in state {status}"
    if detail:
        ET.SubElement(case, "system-out").text = detail
    return case


def _totals(suites: list[ET.Element]) -> tuple[int, int, int]:
    return (
        sum(int(item.get("tests", "0")) for item in suites),
        sum(int(item.get("failures", "0")) for item in suites),
        sum(int(item.get("errors", "0")) for item in suites),
    )


def _float(value: object) -> float:
    try:
        return max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _seconds(value: object) -> str:
    return f"{_float(value):.6f}"
