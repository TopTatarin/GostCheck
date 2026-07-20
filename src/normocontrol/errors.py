"""Project-specific exception hierarchy."""


class NormocontrolError(Exception):
    """Base error for expected GostCheck failures."""


class ConfigurationError(NormocontrolError):
    """Raised when project configuration is invalid."""

