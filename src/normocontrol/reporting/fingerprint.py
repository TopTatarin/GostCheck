"""Path-normalized fingerprints for published findings."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from normocontrol.domain import Finding

_ABS_WIN = re.compile(r"^[A-Za-z]:[\\/]")
_ABS_POSIX = re.compile(r"^/")


def to_repo_relative(path: str | None, repo_root: Path | None) -> str | None:
    """Convert absolute local paths to repo-relative POSIX-ish paths when possible."""
    if path is None or path == "":
        return path
    text = path.replace("\\", "/")
    if repo_root is not None:
        root_text = str(repo_root).replace("\\", "/").rstrip("/")
        if text.lower().startswith(root_text.lower() + "/"):
            return text[len(root_text) + 1 :]
        try:
            resolved = Path(path)
            root_resolved = repo_root
            if resolved.is_absolute():
                relative = Path(text).as_posix()
                root_posix = root_resolved.as_posix().rstrip("/")
                if relative.lower().startswith(root_posix.lower() + "/"):
                    return relative[len(root_posix) + 1 :]
            else:
                return Path(path).as_posix()
        except (OSError, ValueError):
            pass
        lowered = text.lower()
        marker = "/gostcheck/"
        idx = lowered.rfind(marker)
        if idx >= 0:
            return text[idx + len(marker) :]
    if _ABS_WIN.match(path) or _ABS_POSIX.match(text):
        parts = [part for part in text.split("/") if part not in {"", "."}]
        for anchor in ("tests", "src", "docs", "templates", "schemas"):
            if anchor in parts:
                return "/".join(parts[parts.index(anchor) :])
        return parts[-1] if parts else text
    return text


def normalize_finding_payload(
    finding: Finding,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic JSON-ready payload with normalized paths."""
    payload = finding.model_dump(mode="json", exclude_none=True)
    if "path" in payload:
        payload["path"] = to_repo_relative(payload["path"], repo_root)
    evidence = []
    for item in payload.get("evidence", []):
        locator = item.get("locator")
        if isinstance(locator, str):
            if ":" in locator and not locator.startswith(("http://", "https://")):
                # Split only on the last colon when Windows drive is present.
                if _ABS_WIN.match(locator.replace("/", "\\")) or _ABS_WIN.match(locator):
                    file_part, _, rest = locator.replace("\\", "/").rpartition(":")
                else:
                    file_part, _, rest = locator.partition(":")
                    file_part = file_part.replace("\\", "/")
                file_part = to_repo_relative(file_part, repo_root) or file_part
                item = {**item, "locator": f"{file_part}:{rest}" if rest else file_part}
            else:
                item = {
                    **item,
                    "locator": to_repo_relative(locator, repo_root) or locator,
                }
        evidence.append(item)
    if evidence:
        payload["evidence"] = evidence
    return payload


def finding_fingerprint(
    finding: Finding,
    *,
    repo_root: Path | None = None,
) -> str:
    """Stable SHA-256 fingerprint that ignores absolute local path prefixes."""
    payload = normalize_finding_payload(finding, repo_root=repo_root)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
