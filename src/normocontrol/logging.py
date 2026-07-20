"""Safe logging helpers."""

import logging


def configure_logging(verbose: bool = False) -> None:
    """Configure console logging without secrets or document content."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

