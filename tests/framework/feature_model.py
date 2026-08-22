"""Validated registry for executable installed-system feature suites."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .model import Architecture, TestMatrix


@dataclass(frozen=True)
class FeatureSuite:
    id: str
    source_cases: dict[Architecture, str]
    checks: tuple[str, ...]
    isolation: str
    observation_modes: tuple[str, ...]

    def source_for(self, architecture: Architecture) -> str | None:
        return self.source_cases.get(architecture)

    def supports(self, architecture: Architecture) -> bool:
        return architecture in self.source_cases


@dataclass(frozen=True)
class FeatureSuiteRegistry:
    schema_version: int
    suites: tuple[FeatureSuite, ...]

    @classmethod
    def load(cls, path: Path, matrix: TestMatrix) -> "FeatureSuiteRegistry":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                f"Cannot read executable feature-suite registry: {error}"
            ) from error
        if set(raw) != {"schema_version", "suites"} or raw["schema_version"] != 1:
            raise ConfigurationError("Unsupported feature-suite registry schema")
        values = raw["suites"]
        if not isinstance(values, list):
            raise ConfigurationError("Feature-suite registry suites must be a list")
        suites = tuple(_load_suite(value, matrix) for value in values)
        identifiers = [suite.id for suite in suites]
        if len(identifiers) != len(set(identifiers)):
            raise ConfigurationError("Feature-suite registry has duplicate suite IDs")
        check_ids = [check for suite in suites for check in suite.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ConfigurationError(
                "An executable feature check is owned by more than one suite"
            )
        return cls(schema_version=1, suites=suites)

    def select(
        self,
        architecture: Architecture,
        identifiers: tuple[str, ...] = (),
    ) -> tuple[FeatureSuite, ...]:
        known = {suite.id for suite in self.suites}
        unknown = sorted(set(identifiers) - known)
        if unknown:
            raise ConfigurationError(
                "Unknown executable feature suite(s): " + ", ".join(unknown)
            )
        selected = tuple(
            suite
            for suite in self.suites
            if suite.supports(architecture)
            and (not identifiers or suite.id in identifiers)
        )
        if identifiers and len(selected) != len(set(identifiers)):
            unavailable = sorted(set(identifiers) - {suite.id for suite in selected})
            raise ConfigurationError(
                f"Suite(s) do not support {architecture.value}: "
                + ", ".join(unavailable)
            )
        return selected

    @staticmethod
    def validate_sources(
        suites: tuple[FeatureSuite, ...],
        matrix: TestMatrix,
        architecture: Architecture,
        selected_case_ids: set[str],
    ) -> None:
        scenarios = {scenario.id: scenario for scenario in matrix.scenarios}
        missing = []
        for suite in suites:
            source = suite.source_for(architecture)
            if source is None:
                raise ConfigurationError(
                    f"{suite.id}: no source for {architecture.value}"
                )
            scenario = scenarios[source]
            if not scenario.supports(architecture):
                raise ConfigurationError(
                    f"{suite.id}: source {source} does not support "
                    f"{architecture.value}"
                )
            if source not in selected_case_ids:
                missing.append(f"{suite.id} requires installation case {source}")
        if missing:
            raise ConfigurationError(
                "Selected feature suites have no installation base in this run: "
                + "; ".join(missing)
            )


def _load_suite(value: object, matrix: TestMatrix) -> FeatureSuite:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "source_cases",
        "checks",
        "isolation",
        "observation_modes",
    }:
        raise ConfigurationError("Executable feature suite has an invalid shape")
    identifier = value["id"]
    if not isinstance(identifier, str) or not identifier:
        raise ConfigurationError("Feature-suite ID must be a non-empty string")
    raw_sources = value["source_cases"]
    if not isinstance(raw_sources, dict) or not raw_sources:
        raise ConfigurationError(f"{identifier}: source_cases must be an object")
    try:
        sources = {
            Architecture(key): source for key, source in raw_sources.items()
        }
    except ValueError as error:
        raise ConfigurationError(f"{identifier}: invalid source architecture") from error
    scenario_ids = {scenario.id for scenario in matrix.scenarios}
    for architecture, source in sources.items():
        if not isinstance(source, str) or source not in scenario_ids:
            raise ConfigurationError(
                f"{identifier}: unknown source scenario for {architecture.value}"
            )
    raw_checks = value["checks"]
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ConfigurationError(f"{identifier}: checks must be a non-empty list")
    if not all(
        isinstance(check, str) and "." in check and check for check in raw_checks
    ):
        raise ConfigurationError(f"{identifier}: invalid check identifier")
    checks = tuple(raw_checks)
    if len(checks) != len(set(checks)):
        raise ConfigurationError(f"{identifier}: duplicate checks")
    isolation = value["isolation"]
    if isolation != "overlay":
        raise ConfigurationError(
            f"{identifier}: runtime feature suites currently require overlay isolation"
        )
    raw_modes = value["observation_modes"]
    if not isinstance(raw_modes, list) or not raw_modes:
        raise ConfigurationError(
            f"{identifier}: observation_modes must be a non-empty list"
        )
    modes = tuple(raw_modes)
    if not set(modes) <= {"passive", "controlled"}:
        raise ConfigurationError(f"{identifier}: unsupported observation mode")
    return FeatureSuite(
        id=identifier,
        source_cases=sources,
        checks=checks,
        isolation=isolation,
        observation_modes=modes,
    )
