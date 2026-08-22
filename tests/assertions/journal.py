"""Structured journal assertions for unexpected diagnostics."""

from __future__ import annotations

import base64
import fnmatch
import json
import re
import shlex
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from framework.errors import ConfigurationError, TestFailure


_ENTRY_KEYS = {
    "cursor",
    "timestamp",
    "priority",
    "message",
    "identifiers",
}
_CONDITION_NAMES = {
    "automatic_login",
    "desktop_contracts",
    "rime",
}
_ACTION_SCOPE_CONDITION = "action_scope"


@dataclass(frozen=True)
class JournalEntry:
    cursor: str
    timestamp: str
    priority: int
    message: str
    identifiers: tuple[str, ...]
    scopes: tuple[str, ...] = ()

    @property
    def component_text(self) -> str:
        return "|".join(self.identifiers)

    def to_dict(self) -> dict[str, object]:
        return {
            "cursor": self.cursor,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "message": self.message,
            "identifiers": list(self.identifiers),
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class KnownDiagnostic:
    id: str
    component_regex: str
    message_regex: str
    conditions: dict[str, object]
    max_occurrences: int
    package: str
    version_glob: str
    owner: str
    reason: str

    def entry_matches(self, entry: JournalEntry) -> bool:
        return bool(
            re.search(self.component_regex, entry.component_text, re.IGNORECASE)
            and re.search(self.message_regex, entry.message, re.IGNORECASE)
        )

    def applies(
        self,
        scenario: object,
        package_versions: dict[str, str],
        action_scope: str,
    ) -> bool:
        for name, expected in self.conditions.items():
            actual = (
                action_scope
                if name == _ACTION_SCOPE_CONDITION
                else getattr(scenario, name, None)
            )
            if hasattr(actual, "value"):
                actual = actual.value
            if actual != expected:
                return False
        version = package_versions.get(self.package, "")
        return bool(version and fnmatch.fnmatchcase(version, self.version_glob))


@dataclass(frozen=True)
class JournalFinding:
    kind: str
    reason: str
    entry: JournalEntry | None = None
    rule_id: str = ""

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "kind": self.kind,
            "reason": self.reason,
        }
        if self.rule_id:
            result["rule_id"] = self.rule_id
        if self.entry is not None:
            result["entry"] = self.entry.to_dict()
        return result


@dataclass(frozen=True)
class JournalVerdict:
    blockers: tuple[JournalFinding, ...]
    known_diagnostics: tuple[JournalFinding, ...]
    observations: tuple[JournalFinding, ...]
    candidate_count: int

    @property
    def passed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "passed": self.passed,
            "summary": {
                "candidates": self.candidate_count,
                "blockers": len(self.blockers),
                "known_diagnostics": len(self.known_diagnostics),
                "observations": len(self.observations),
            },
            "blockers": [item.to_dict() for item in self.blockers],
            "known_diagnostics": [
                item.to_dict() for item in self.known_diagnostics
            ],
            "observations": [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True)
class JournalPolicy:
    fatal_message_patterns: tuple[str, ...]
    known_diagnostics: tuple[KnownDiagnostic, ...]

    @classmethod
    def load(cls, path: Path) -> "JournalPolicy":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"Cannot read journal policy: {error}") from error
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version",
            "fatal_message_patterns",
            "known_diagnostics",
        }:
            raise ConfigurationError("Journal policy has an invalid top-level shape")
        if raw["schema_version"] != 1:
            raise ConfigurationError("Unsupported journal policy schema")
        patterns = raw["fatal_message_patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise ConfigurationError("Journal policy has no fatal message patterns")
        if not all(isinstance(item, str) and item for item in patterns):
            raise ConfigurationError("Journal fatal patterns must be non-empty strings")
        _compile_patterns(patterns, "fatal message")
        diagnostics = raw["known_diagnostics"]
        if not isinstance(diagnostics, list):
            raise ConfigurationError("Journal known diagnostics must be a list")
        loaded = tuple(_load_known_diagnostic(item) for item in diagnostics)
        identifiers = [item.id for item in loaded]
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationError("Journal policy contains duplicate diagnostic IDs")
        return cls(tuple(patterns), loaded)

    @property
    def candidate_patterns(self) -> tuple[str, ...]:
        return self.fatal_message_patterns + tuple(
            item.message_regex for item in self.known_diagnostics
        )

    @property
    def packages(self) -> tuple[str, ...]:
        return tuple(sorted({item.package for item in self.known_diagnostics}))

    def classify(
        self,
        entries: Iterable[JournalEntry],
        scenario: object,
        package_versions: dict[str, str],
        *,
        failed_system_units: Iterable[str] = (),
        failed_user_units: Iterable[str] = (),
        action_scope: str = "",
    ) -> JournalVerdict:
        merged = merge_journal_entries(entries)
        blockers: list[JournalFinding] = []
        known: list[JournalFinding] = []
        observations: list[JournalFinding] = []
        counts: dict[str, int] = {}

        for scope, units in (
            ("system", failed_system_units),
            ("user", failed_user_units),
        ):
            for unit in units:
                if unit.strip():
                    blockers.append(
                        JournalFinding(
                            "failed-unit",
                            f"{scope} systemd unit failed: {unit.strip()}",
                        )
                    )

        fatal_patterns = _compile_patterns(
            self.fatal_message_patterns,
            "fatal message",
        )
        for entry in merged:
            matching_rule = next(
                (
                    rule
                    for rule in self.known_diagnostics
                    if rule.entry_matches(entry)
                    and rule.applies(scenario, package_versions, action_scope)
                ),
                None,
            )
            if matching_rule is not None:
                occurrence = counts.get(matching_rule.id, 0) + 1
                counts[matching_rule.id] = occurrence
                if occurrence <= matching_rule.max_occurrences:
                    known.append(
                        JournalFinding(
                            "known-diagnostic",
                            f"{matching_rule.owner}: {matching_rule.reason}",
                            entry,
                            matching_rule.id,
                        )
                    )
                    continue
                blockers.append(
                    JournalFinding(
                        "diagnostic-budget-exceeded",
                        f"Known diagnostic {matching_rule.id!r} occurred "
                        f"{occurrence} times; policy permits "
                        f"{matching_rule.max_occurrences}",
                        entry,
                        matching_rule.id,
                    )
                )
                continue

            fatal = entry.priority <= 3 or any(
                pattern.search(entry.message) for pattern in fatal_patterns
            )
            if fatal:
                blockers.append(
                    JournalFinding(
                        "unexpected-journal-error",
                        _unmatched_reason(
                            entry,
                            self.known_diagnostics,
                            scenario,
                            package_versions,
                        ),
                        entry,
                    )
                )
            else:
                observations.append(
                    JournalFinding(
                        "journal-observation",
                        "Candidate did not match a release-blocking rule",
                        entry,
                    )
                )

        return JournalVerdict(
            tuple(blockers),
            tuple(known),
            tuple(observations),
            len(merged),
        )


def render_guest_collection_script(
    policy: JournalPolicy,
    *,
    user: bool = False,
    after_cursor: str | None = None,
) -> str:
    """Return a guest command that emits structured candidate entries.

    ``after_cursor`` deliberately scopes a functional check to journal entries
    created after the action began.  The cursor is passed as one quoted
    argument to journalctl; callers never interpolate it into a shell program.
    """

    patterns = base64.b64encode(
        json.dumps(policy.candidate_patterns).encode("utf-8")
    ).decode("ascii")
    program = f"""
import base64
import json
import re
import sys

patterns = json.loads(base64.b64decode({patterns!r}).decode('utf-8'))
compiled = [re.compile(item, re.IGNORECASE) for item in patterns]
keys = ('SYSLOG_IDENTIFIER', '_COMM', '_SYSTEMD_UNIT',
        '_SYSTEMD_USER_UNIT', '_EXE')
for raw_line in sys.stdin:
    try:
        raw = json.loads(raw_line)
    except json.JSONDecodeError:
        continue
    message = raw.get('MESSAGE', '')
    if isinstance(message, list):
        message = ' '.join(str(item) for item in message)
    else:
        message = str(message)
    try:
        priority = int(raw.get('PRIORITY', 7))
    except (TypeError, ValueError):
        priority = 7
    if priority > 3 and not any(item.search(message) for item in compiled):
        continue
    identifiers = []
    for key in keys:
        value = raw.get(key)
        if value and str(value) not in identifiers:
            identifiers.append(str(value))
    normalized = {{
        'cursor': str(raw.get('__CURSOR', '')),
        'timestamp': str(raw.get('__REALTIME_TIMESTAMP', '')),
        'priority': priority,
        'message': message,
        'identifiers': identifiers,
    }}
    print(json.dumps(normalized, ensure_ascii=False, sort_keys=True))
""".strip()
    journal_scope = " --user" if user else ""
    cursor_scope = (
        f" --after-cursor={shlex.quote(after_cursor)}"
        if after_cursor is not None
        else ""
    )
    return (
        "set -o pipefail\n"
        f"journalctl{journal_scope} -b{cursor_scope} --no-pager -o json | "
        f"python3 -c {shlex.quote(program)}"
    )


def parse_journal_jsonl(value: str, scope: str) -> tuple[JournalEntry, ...]:
    entries: list[JournalEntry] = []
    for number, raw_line in enumerate(value.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise TestFailure(
                f"Malformed {scope} journal JSON on line {number}: {error}"
            ) from error
        if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
            raise TestFailure(
                f"Malformed {scope} journal entry shape on line {number}"
            )
        identifiers = raw["identifiers"]
        if not isinstance(identifiers, list) or not all(
            isinstance(item, str) and item for item in identifiers
        ):
            raise TestFailure(
                f"Malformed {scope} journal identifiers on line {number}"
            )
        priority = raw["priority"]
        if type(priority) is not int or not 0 <= priority <= 7:
            raise TestFailure(
                f"Malformed {scope} journal priority on line {number}"
            )
        for name in ("cursor", "timestamp", "message"):
            if not isinstance(raw[name], str):
                raise TestFailure(
                    f"Malformed {scope} journal {name} on line {number}"
                )
        entries.append(
            JournalEntry(
                cursor=raw["cursor"],
                timestamp=raw["timestamp"],
                priority=priority,
                message=raw["message"],
                identifiers=tuple(identifiers),
                scopes=(scope,),
            )
        )
    return tuple(entries)


def merge_journal_entries(
    entries: Iterable[JournalEntry],
) -> tuple[JournalEntry, ...]:
    merged: dict[object, JournalEntry] = {}
    for entry in entries:
        key: object = entry.cursor or (
            entry.timestamp,
            entry.priority,
            entry.message,
            entry.identifiers,
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry
            continue
        scopes = tuple(sorted(set(existing.scopes) | set(entry.scopes)))
        merged[key] = replace(existing, scopes=scopes)
    return tuple(merged.values())


def parse_package_versions(value: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in value.splitlines():
        if not raw_line.strip():
            continue
        package, separator, version = raw_line.partition("\t")
        if not separator or not package or not version:
            raise TestFailure(f"Malformed package-version evidence: {raw_line!r}")
        versions[package] = version
    return versions


def render_verdict(verdict: JournalVerdict) -> str:
    lines = [
        "Journal release verdict: " + ("PASS" if verdict.passed else "FAIL"),
        f"Candidates: {verdict.candidate_count}",
        f"Blockers: {len(verdict.blockers)}",
        f"Known diagnostics: {len(verdict.known_diagnostics)}",
        f"Observations: {len(verdict.observations)}",
    ]
    for heading, findings in (
        ("BLOCKERS", verdict.blockers),
        ("KNOWN DIAGNOSTICS", verdict.known_diagnostics),
        ("OBSERVATIONS", verdict.observations),
    ):
        lines.append(f"\n=== {heading} ===")
        if not findings:
            lines.append("none")
            continue
        for finding in findings:
            rule = f" [{finding.rule_id}]" if finding.rule_id else ""
            lines.append(f"- {finding.kind}{rule}: {finding.reason}")
            if finding.entry is not None:
                lines.append(
                    "  priority="
                    f"{finding.entry.priority} component="
                    f"{finding.entry.component_text or '<unknown>'}"
                )
                lines.append(f"  message={finding.entry.message}")
    return "\n".join(lines) + "\n"


def _load_known_diagnostic(value: object) -> KnownDiagnostic:
    required = {
        "id",
        "component_regex",
        "message_regex",
        "conditions",
        "max_occurrences",
        "package",
        "version_glob",
        "owner",
        "reason",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ConfigurationError("Journal diagnostic has an invalid shape")
    string_names = required - {"conditions", "max_occurrences"}
    for name in string_names:
        if not isinstance(value[name], str) or not value[name]:
            raise ConfigurationError(
                f"Journal diagnostic {name} must be a non-empty string"
            )
    conditions = value["conditions"]
    if not isinstance(conditions, dict) or not conditions:
        raise ConfigurationError("Journal diagnostic conditions must be an object")
    if not set(conditions) <= _CONDITION_NAMES | {_ACTION_SCOPE_CONDITION}:
        raise ConfigurationError("Journal diagnostic has an unknown condition")
    for name, item in conditions.items():
        if name == _ACTION_SCOPE_CONDITION:
            if not isinstance(item, str) or not item:
                raise ConfigurationError(
                    "Journal diagnostic action_scope must be a non-empty string"
                )
        elif type(item) is not bool:
            raise ConfigurationError(
                "Journal diagnostic scenario conditions must be booleans"
            )
    maximum = value["max_occurrences"]
    if type(maximum) is not int or maximum <= 0:
        raise ConfigurationError(
            "Journal diagnostic max_occurrences must be positive"
        )
    _compile_patterns(
        (value["component_regex"], value["message_regex"]),
        f"diagnostic {value['id']}",
    )
    return KnownDiagnostic(
        id=value["id"],
        component_regex=value["component_regex"],
        message_regex=value["message_regex"],
        conditions=dict(conditions),
        max_occurrences=maximum,
        package=value["package"],
        version_glob=value["version_glob"],
        owner=value["owner"],
        reason=value["reason"],
    )


def _compile_patterns(
    patterns: Iterable[str],
    label: str,
) -> tuple[re.Pattern[str], ...]:
    try:
        return tuple(re.compile(item, re.IGNORECASE) for item in patterns)
    except re.error as error:
        raise ConfigurationError(f"Invalid journal {label} regex: {error}") from error


def _unmatched_reason(
    entry: JournalEntry,
    rules: Iterable[KnownDiagnostic],
    scenario: object,
    package_versions: dict[str, str],
) -> str:
    near = [rule for rule in rules if rule.entry_matches(entry)]
    if near:
        details = []
        for rule in near:
            version = package_versions.get(rule.package, "<missing>")
            details.append(
                f"{rule.id} does not apply to this scenario/action scope or "
                f"{rule.package}={version} (allowed {rule.version_glob})"
            )
        return "; ".join(details)
    if entry.priority <= 3:
        return f"Unexpected journal priority {entry.priority} entry"
    return "Unexpected fatal journal message"
