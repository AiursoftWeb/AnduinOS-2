"""Typed failures emitted by the ISO acceptance framework."""


class AcceptanceError(RuntimeError):
    """Base class for an actionable acceptance-test failure."""


class ConfigurationError(AcceptanceError):
    """The host, ISO, firmware, or requested matrix is invalid."""


class ProtocolError(AcceptanceError):
    """QMP or the guest serial protocol returned invalid data."""


class TestFailure(AcceptanceError):
    """The guest booted but did not satisfy an acceptance requirement."""
