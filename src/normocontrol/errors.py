"""Project-specific exception hierarchy."""

from normocontrol.logging import redact_text


class NormocontrolError(Exception):
    """Base error for expected GostCheck failures."""

    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


class ConfigurationError(NormocontrolError):
    """Raised when project configuration is invalid."""


class LocatedValidationError(ConfigurationError):
    """A user-facing validation error tied to a file and YAML path."""

    def __init__(self, message: str, *, source: str, yaml_path: str = "$") -> None:
        self.source = source
        self.yaml_path = yaml_path
        super().__init__(f"{source}:{yaml_path}: {message}")


class RubricValidationError(LocatedValidationError):
    """Raised when ``rubric.yaml`` violates its public contract."""


class ConfigValidationError(LocatedValidationError):
    """Raised when normocontrol configuration cannot be resolved."""
