import logging

from normocontrol.errors import ConfigurationError, NormocontrolError
from normocontrol.logging import configure_logging


def test_configuration_error_uses_project_base_error() -> None:
    error = ConfigurationError("invalid profile")

    assert isinstance(error, NormocontrolError)
    assert str(error) == "invalid profile"


def test_configure_logging_selects_debug_level(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging(verbose=True)

    assert captured["level"] == logging.DEBUG
    assert "%(message)s" in str(captured["format"])
