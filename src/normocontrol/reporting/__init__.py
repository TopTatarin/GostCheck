"""Public reporting package for published JSON/Markdown artifacts."""

from normocontrol.reporting.aggregate import PublishResult, publish_reports
from normocontrol.reporting.console import (
    ConsoleRunSummary,
    build_console_summary,
    build_error_console_summary,
    render_console_summary,
    safe_display_path,
)
from normocontrol.reporting.fingerprint import finding_fingerprint
from normocontrol.reporting.json_report import ReportMeta, build_published_report

__all__ = [
    "ConsoleRunSummary",
    "PublishResult",
    "ReportMeta",
    "build_console_summary",
    "build_error_console_summary",
    "build_published_report",
    "finding_fingerprint",
    "publish_reports",
    "render_console_summary",
    "safe_display_path",
]
