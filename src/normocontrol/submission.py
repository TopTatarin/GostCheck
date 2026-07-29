"""Privacy-safe discovery and validation of submitted PDF/LaTeX inputs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from normocontrol.errors import ConfigurationError
from normocontrol.extract.latex import (
    _INCLUDE_RE,
    _protect_literal_environments,
    _strip_comments,
)

_CLASS_RE = re.compile(
    r"\\documentclass\s*(?:\[[^\]]*\]\s*)?\{(?P<value>[^{}]+)\}",
    re.IGNORECASE,
)
_STYLE_RE = re.compile(
    r"\\usepackage\s*(?:\[[^\]]*\]\s*)?\{(?P<value>[^{}]+)\}",
    re.IGNORECASE,
)
_BIBLIOGRAPHY_RE = re.compile(
    r"\\(?:addbibresource|bibliography)\s*"
    r"(?:\[[^\]]*\]\s*)?\{(?P<value>[^{}]+)\}",
    re.IGNORECASE,
)
_IMAGE_RE = re.compile(
    r"\\includegraphics\*?\s*(?:\[[^\]]*\]\s*)?\{(?P<value>[^{}]+)\}",
    re.IGNORECASE,
)
_STANDARD_CLASSES = frozenset(
    {
        "article",
        "beamer",
        "book",
        "extarticle",
        "extbook",
        "extreport",
        "letter",
        "memoir",
        "minimal",
        "proc",
        "report",
        "scrartcl",
        "scrbook",
        "scrreprt",
        "slides",
        "standalone",
    }
)
_IMAGE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")
_DIAGNOSTIC_ORDER = {
    "include": 0,
    "class": 1,
    "style": 2,
    "bibliography": 3,
    "image": 4,
}


@dataclass(frozen=True, slots=True)
class ResolvedSubmission:
    """One validated input file and the directory that bounds its dependencies."""

    source: Path
    root: Path
    relative_source: str


@dataclass(frozen=True, slots=True)
class SubmissionDiagnostic:
    """A content-free diagnostic for one missing local dependency."""

    kind: str
    path: str


def _path_key(path: Path, root: Path) -> tuple[str, str]:
    relative = path.relative_to(root).as_posix()
    return unicodedata.normalize("NFC", relative).casefold(), relative


def _safe_name(path: Path, fallback: str = "input") -> str:
    return path.name or fallback


def _resolve_inside(candidate: Path, root: Path, *, label: str) -> Path:
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise ConfigurationError(f"{label} not found: {_safe_name(candidate)}") from error
    if not resolved.is_relative_to(root):
        raise ConfigurationError(
            f"{label} resolves outside project root (outside submission root): "
            f"{_safe_name(candidate)}"
        )
    if not resolved.is_file():
        raise ConfigurationError(f"{label} is not a file: {_safe_name(candidate)}")
    return resolved


def _validate_relative_root(root: Path) -> None:
    portable = root.as_posix()
    windows = PureWindowsPath(str(root))
    if (
        root.is_absolute()
        or PurePosixPath(portable).is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
    ):
        raise ConfigurationError("--root must be relative to the submission directory")
    if ".." in PurePosixPath(portable).parts or ".." in windows.parts:
        raise ConfigurationError("--root path traversal is not allowed")


def resolve_submission(source: Path, *, root: Path | None = None) -> ResolvedSubmission:
    """Resolve a PDF or unambiguous LaTeX root without exposing host paths."""
    try:
        source_root = source.resolve(strict=True)
    except FileNotFoundError as error:
        raise ConfigurationError(f"source path does not exist: {_safe_name(source)}") from error

    if source_root.is_file():
        if root is not None:
            raise ConfigurationError("--root is only valid when the input is a directory")
        if source_root.suffix.casefold() not in {".tex", ".pdf"}:
            raise ConfigurationError("supported source extensions are .tex and .pdf")
        return ResolvedSubmission(
            source=source_root,
            root=source_root.parent,
            relative_source=source_root.name,
        )
    if not source_root.is_dir():
        raise ConfigurationError(f"source path is not a file or directory: {_safe_name(source)}")

    if root is not None:
        _validate_relative_root(root)
        resolved = _resolve_inside(source_root / root, source_root, label="LaTeX root")
        if resolved.suffix.casefold() != ".tex":
            raise ConfigurationError("--root must name a .tex file")
        return ResolvedSubmission(
            source=resolved,
            root=source_root,
            relative_source=resolved.relative_to(source_root).as_posix(),
        )

    top_level_main = source_root / "main.tex"
    if top_level_main.is_file():
        resolved = _resolve_inside(top_level_main, source_root, label="LaTeX root")
        return ResolvedSubmission(source=resolved, root=source_root, relative_source="main.tex")

    candidates: list[Path] = []
    for candidate in source_root.rglob("*.tex"):
        if candidate.name.casefold() != "main.tex":
            continue
        resolved = _resolve_inside(candidate, source_root, label="LaTeX root")
        candidates.append(resolved)
    candidates = sorted(set(candidates), key=lambda item: _path_key(item, source_root))
    if len(candidates) == 1:
        resolved = candidates[0]
        return ResolvedSubmission(
            source=resolved,
            root=source_root,
            relative_source=resolved.relative_to(source_root).as_posix(),
        )
    if len(candidates) > 1:
        relative = ", ".join(path.relative_to(source_root).as_posix() for path in candidates)
        raise ConfigurationError(f"multiple LaTeX roots found: {relative}; select one with --root")

    top_level_pdf = source_root / "main.pdf"
    if top_level_pdf.is_file():
        resolved = _resolve_inside(top_level_pdf, source_root, label="PDF input")
        return ResolvedSubmission(source=resolved, root=source_root, relative_source="main.pdf")

    raise ConfigurationError(
        "LaTeX root main.tex not found; use --root <relative-root.tex> "
        "or provide a complete LaTeX project bundle"
    )


def _portable_reference(reference: str, *, kind: str) -> PurePosixPath:
    value = reference.strip().replace("\\", "/")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(reference.strip())
    display = posix.name or kind
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
    ):
        raise ConfigurationError(f"{kind} path must be relative: {display}")
    if ".." in posix.parts:
        raise ConfigurationError(f"{kind} path traversal is not allowed: {display}")
    return posix


def _display_reference(reference: str, *, suffix: str | None = None) -> str:
    portable = reference.strip().replace("\\", "/")
    path = PurePosixPath(portable)
    if suffix is not None and path.suffix == "":
        path = path.with_suffix(suffix)
    return path.as_posix()


def _dependency_candidates(
    root: Path,
    current: Path,
    reference: str,
    *,
    kind: str,
    suffixes: tuple[str, ...],
) -> tuple[Path, ...]:
    posix = _portable_reference(reference, kind=kind)
    relative = Path(*posix.parts)
    bases = (current.parent, root) if current.parent != root else (root,)
    candidates: list[Path] = []
    for base in bases:
        candidate = base / relative
        if candidate.suffix:
            candidates.append(candidate)
        else:
            candidates.extend(candidate.with_suffix(suffix) for suffix in suffixes)
    return tuple(dict.fromkeys(candidates))


def _dependency_exists(candidates: tuple[Path, ...], root: Path, *, kind: str) -> bool:
    for candidate in candidates:
        if not candidate.exists():
            continue
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ConfigurationError(
                f"{kind} resolves outside project root (outside submission root): "
                f"{_safe_name(candidate)}"
            )
        if resolved.is_file():
            return True
    return False


def _active_source(path: Path, root: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ConfigurationError(f"LaTeX source not found: {_safe_name(path)}") from error
    if not resolved.is_relative_to(root):
        raise ConfigurationError(
            "LaTeX source resolves outside project root "
            f"(outside submission root): {_safe_name(path)}"
        )
    try:
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        relative = resolved.relative_to(root).as_posix()
        raise ConfigurationError(f"cannot read UTF-8 LaTeX source: {relative}") from error
    opaque, _protected = _protect_literal_environments(raw)
    return _strip_comments(opaque)


def _is_dynamic(reference: str) -> bool:
    return any(token in reference for token in ("\\", "#", "{", "}"))


def _collect_dependency_diagnostics(
    root: Path,
    current: Path,
    *,
    visited: frozenset[Path],
) -> tuple[SubmissionDiagnostic, ...]:
    resolved_current = current.resolve(strict=True)
    if resolved_current in visited:
        return ()
    active = _active_source(resolved_current, root)
    diagnostics: list[SubmissionDiagnostic] = []
    next_visited = visited | frozenset({resolved_current})

    for match in _INCLUDE_RE.finditer(active):
        reference = (match.group("braced") or match.group("bare")).strip()
        if _is_dynamic(reference):
            continue
        candidates = _dependency_candidates(
            root,
            resolved_current,
            reference,
            kind="include",
            suffixes=(".tex",),
        )
        if not _dependency_exists(candidates, root, kind="include"):
            diagnostics.append(
                SubmissionDiagnostic(
                    kind="include",
                    path=_display_reference(reference, suffix=".tex"),
                )
            )
            continue
        child = next(
            candidate.resolve(strict=True) for candidate in candidates if candidate.exists()
        )
        diagnostics.extend(_collect_dependency_diagnostics(root, child, visited=next_visited))

    for match in _CLASS_RE.finditer(active):
        reference = match.group("value").strip()
        if _is_dynamic(reference) or reference.casefold() in _STANDARD_CLASSES:
            continue
        candidates = _dependency_candidates(
            root,
            resolved_current,
            reference,
            kind="class",
            suffixes=(".cls",),
        )
        if not _dependency_exists(candidates, root, kind="class"):
            diagnostics.append(
                SubmissionDiagnostic(
                    kind="class",
                    path=_display_reference(reference, suffix=".cls"),
                )
            )

    for match in _STYLE_RE.finditer(active):
        for reference in (item.strip() for item in match.group("value").split(",")):
            if (
                not reference
                or _is_dynamic(reference)
                or ("/" not in reference and "\\" not in reference and "." not in reference)
            ):
                continue
            candidates = _dependency_candidates(
                root,
                resolved_current,
                reference,
                kind="style",
                suffixes=(".sty",),
            )
            if not _dependency_exists(candidates, root, kind="style"):
                diagnostics.append(
                    SubmissionDiagnostic(
                        kind="style",
                        path=_display_reference(reference, suffix=".sty"),
                    )
                )

    for match in _BIBLIOGRAPHY_RE.finditer(active):
        references = (
            match.group("value").split(",")
            if match.group(0).casefold().startswith("\\bibliography")
            else (match.group("value"),)
        )
        for reference in (item.strip() for item in references):
            if not reference or _is_dynamic(reference):
                continue
            candidates = _dependency_candidates(
                root,
                resolved_current,
                reference,
                kind="bibliography",
                suffixes=(".bib",),
            )
            if not _dependency_exists(candidates, root, kind="bibliography"):
                diagnostics.append(
                    SubmissionDiagnostic(
                        kind="bibliography",
                        path=_display_reference(reference, suffix=".bib"),
                    )
                )

    for match in _IMAGE_RE.finditer(active):
        reference = match.group("value").strip()
        if not reference or _is_dynamic(reference):
            continue
        candidates = _dependency_candidates(
            root,
            resolved_current,
            reference,
            kind="image",
            suffixes=_IMAGE_SUFFIXES,
        )
        if not _dependency_exists(candidates, root, kind="image"):
            diagnostics.append(
                SubmissionDiagnostic(kind="image", path=_display_reference(reference))
            )
    return tuple(diagnostics)


def validate_latex_bundle(
    project_root: Path,
    main_tex: Path,
) -> tuple[SubmissionDiagnostic, ...]:
    """Reject missing active local dependencies with deterministic safe diagnostics."""
    try:
        root = project_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise ConfigurationError("submission root does not exist") from error
    resolved_main = _resolve_inside(main_tex, root, label="LaTeX root")
    diagnostics = _collect_dependency_diagnostics(root, resolved_main, visited=frozenset())
    unique = {(item.kind, item.path): item for item in diagnostics}
    ordered = tuple(
        unique[key]
        for key in sorted(
            unique,
            key=lambda item: (
                _DIAGNOSTIC_ORDER[item[0]],
                unicodedata.normalize("NFC", item[1]).casefold(),
                item[1],
            ),
        )
    )
    if ordered:
        details = "; ".join(f"missing {item.kind}: {item.path}" for item in ordered)
        raise ConfigurationError(f"incomplete LaTeX project bundle: {details}")
    return ordered
