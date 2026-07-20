"""Project-specific exception hierarchy."""

from normocontrol.logging import redact_text


class NormocontrolError(Exception):
    """Base error for expected GostCheck failures."""

    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


class ConfigurationError(NormocontrolError):
    """Raised when project configuration is invalid."""
