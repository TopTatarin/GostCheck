"""Atomic stage cache and output-directory locking for orchestrator runs."""

from __future__ import annotations

import hashlib
import json
import os
import time
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from normocontrol.errors import ConfigurationError, NormocontrolError

LOCK_NAME = ".normocontrol.lock"
CACHE_DIR_NAME = "cache"
DEFAULT_STALE_LOCK_S = 3_600.0


class CacheError(NormocontrolError):
    """Raised when cache state is corrupt or unusable."""


class LockError(NormocontrolError):
    """Raised when the output directory lock cannot be acquired safely."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def hash_text(value: str) -> str:
    """Return SHA-256 hex digest of UTF-8 text."""
    return _sha256_bytes(value.encode("utf-8"))


def hash_paths(paths: Iterable[Path], *, root: Path | None = None) -> str:
    """Hash existing files by stable POSIX path and content."""
    digest = hashlib.sha256()
    resolved_root = root.resolve(strict=True) if root is not None else None
    entries: list[tuple[str, Path]] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        if resolved_root is None:
            label = resolved.as_posix()
        else:
            if not resolved.is_relative_to(resolved_root):
                raise ValueError(f"cache input resolves outside root: {path.name}")
            label = resolved.relative_to(resolved_root).as_posix()
        entries.append((label, resolved))
    for label, path in sorted(
        entries,
        key=lambda item: (unicodedata.normalize("NFC", item[0]).casefold(), item[0]),
    ):
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(hash_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` atomically via a temporary sibling file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding, newline="\n")
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Serialize ``payload`` as deterministic UTF-8 JSON and write atomically."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, text)


@dataclass(frozen=True, slots=True)
class CacheKeyParts:
    """Inputs that uniquely identify a cached stage result."""

    source_hash: str
    rubric_hash: str
    config_hash: str
    tool_version: str
    model_hash: str = "none"
    prompt_hash: str = "none"
    stage: str = ""

    def digest(self) -> str:
        """Stable cache key digest."""
        material = "|".join(
            (
                self.stage,
                self.source_hash,
                self.rubric_hash,
                self.config_hash,
                self.tool_version,
                self.model_hash,
                self.prompt_hash,
            )
        )
        return hash_text(material)


class StageCache:
    """Filesystem cache with model-isolated LLM entries and atomic writes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: CacheKeyParts) -> Path:
        """Return the JSON path for a cache key."""
        namespace = "llm" if key.stage == "semantic" else "deterministic"
        return self.root / namespace / f"{key.digest()}.json"

    def get(self, key: CacheKeyParts) -> dict[str, Any] | None:
        """Load a cache entry or return ``None`` on miss/corruption."""
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            path.unlink(missing_ok=True)
            raise CacheError(f"corrupt cache entry removed: {path.name}") from error
        if not isinstance(payload, dict):
            path.unlink(missing_ok=True)
            raise CacheError(f"corrupt cache entry removed: {path.name}")
        stored_key = payload.get("cache_key")
        if stored_key != key.digest():
            path.unlink(missing_ok=True)
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    def put(self, key: CacheKeyParts, data: Mapping[str, Any]) -> Path:
        """Store a stage payload under an atomic cache entry."""
        path = self.path_for(key)
        atomic_write_json(
            path,
            {
                "cache_key": key.digest(),
                "stage": key.stage,
                "tool_version": key.tool_version,
                "model_hash": key.model_hash,
                "data": dict(data),
            },
        )
        return path

    def invalidate(self) -> None:
        """Delete every cached entry under this cache root."""
        if not self.root.exists():
            return
        for path in self.root.rglob("*.json"):
            path.unlink(missing_ok=True)


class OutputLock:
    """Exclusive lock file preventing concurrent runs on the same ``--out``."""

    def __init__(
        self,
        out_dir: Path,
        *,
        stale_after_s: float = DEFAULT_STALE_LOCK_S,
        pid: int | None = None,
    ) -> None:
        self.out_dir = out_dir
        self.lock_path = out_dir / LOCK_NAME
        self.stale_after_s = stale_after_s
        self.pid = os.getpid() if pid is None else pid
        self._held = False

    def acquire(self) -> None:
        """Create the lock file or reclaim a stale one."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            if self._is_stale():
                self.lock_path.unlink(missing_ok=True)
            else:
                raise LockError(f"output directory is locked: {self.lock_path}")
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise LockError(f"output directory is locked: {self.lock_path}") from error
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(f"pid={self.pid}\ncreated_at={time.time():.3f}\n")
        self._held = True

    def release(self) -> None:
        """Remove the lock file if this instance holds it."""
        if not self._held:
            return
        self.lock_path.unlink(missing_ok=True)
        self._held = False

    def _is_stale(self) -> bool:
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except OSError:
            return True
        return age >= self.stale_after_s

    def __enter__(self) -> OutputLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def ensure_writable_out_dir(out_dir: Path) -> None:
    """Validate that ``out_dir`` exists or can be created and is writable."""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / f".write_probe.{os.getpid()}"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as error:
        raise ConfigurationError(f"output directory is not writable: {out_dir}") from error
