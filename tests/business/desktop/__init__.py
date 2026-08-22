"""Installed-desktop acceptance business layer."""

# Re-export shared module objects and evidence oracles for fault-injection tests.
from .context import *
from .runner import FeatureSuiteResult, FeatureSuiteRunner


__all__ = ("FeatureSuiteResult", "FeatureSuiteRunner")
