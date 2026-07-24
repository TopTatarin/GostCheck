"""LaTeX project loading helpers for formal rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from normocontrol.extract.base import Section, SourceFile, sha256_bytes
from normocontrol.extract.latex import (
    _INCLUDE_RE,
    LatexExtractor,
    _protect_literal_environments,
    _restore_protected,
    _strip_comments,
)

_DOCUMENT_BEGIN_RE = re.compile(r"\\begin\s*\{document\}", re.IGNORECASE)
_LIST_ENV_RE = re.compile(r"\\begin\s*\{(itemize|enumerate)\}", re.IGNORECASE)
_SUBSUBSECTION_RE = re.compile(r"\\subsubsection\b")
_CLASS_FILE_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}")
_USEPACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}")


@dataclass(frozen=True, slots=True)
class LatexProjectSnapshot:
    """Expanded LaTeX sources without embedding thesis text in logs."""

    root: Path
    main_tex: Path
    preamble: str
    body: str
    source_files: tuple[SourceFile, ...]
    sections: tuple[Section, ...]


class LatexProjectReader:
    """Expand a local LaTeX project similarly to the extract stage."""

    def __init__(self, project: LatexProjectSnapshot) -> None:
        self.snapshot = project

    @classmethod
    def load(cls, root: Path, main_tex: Path) -> LatexProjectReader:
        extractor = LatexExtractor(root)
        bundle = extractor.extract(main_tex)
        expanded = cls._expand_for_analysis(root, main_tex)
        match = _DOCUMENT_BEGIN_RE.search(expanded)
        if match is None:
            preamble = expanded
            body = ""
        else:
            preamble = expanded[: match.start()]
            body = expanded[match.end() :]
        return cls(
            LatexProjectSnapshot(
                root=root.resolve(),
                main_tex=main_tex.resolve(),
                preamble=preamble,
                body=body,
                source_files=bundle.source_files,
                sections=bundle.sections,
            )
        )

    @staticmethod
    def _expand_for_analysis(root: Path, main_tex: Path) -> str:
        seen: set[Path] = set()

        def expand(path: Path, stack: tuple[Path, ...]) -> str:
            resolved = path.resolve()
            if resolved in stack:
                return ""
            payload = resolved.read_bytes()
            if resolved not in seen:
                seen.add(resolved)
            raw = payload.decode("utf-8")
            opaque, protected = _protect_literal_environments(raw)
            stripped = _strip_comments(opaque)
            output: list[str] = []
            cursor = 0
            for match in _INCLUDE_RE.finditer(stripped):
                output.append(stripped[cursor : match.start()])
                include_name = (match.group("braced") or match.group("bare")).strip()
                child = (resolved.parent / include_name).resolve()
                if child.suffix == "":
                    child = child.with_suffix(".tex")
                output.append(expand(child, (*stack, resolved)))
                cursor = match.end()
            output.append(stripped[cursor:])
            return _restore_protected("".join(output), protected)

        text = expand(main_tex.resolve(), ())
        return text

    def section_body(self, title: str) -> str | None:
        """Return raw LaTeX body for the first section with a matching title."""
        pattern = re.compile(
            rf"\\section\*?\{{[^{{}}]*{re.escape(title)}[^{{}}]*\}}",
            re.IGNORECASE,
        )
        match = pattern.search(self.snapshot.body)
        if match is None:
            return None
        start = match.end()
        next_section = re.search(r"\\section\*?\{", self.snapshot.body[start:])
        end = start + next_section.start() if next_section else len(self.snapshot.body)
        return self.snapshot.body[start:end]

    def contains_list_environment(self, text: str) -> bool:
        opaque, protected = _protect_literal_environments(text)
        stripped = _strip_comments(opaque)
        restored = _restore_protected(stripped, protected)
        return _LIST_ENV_RE.search(restored) is not None

    def contains_subsubsection(self) -> bool:
        opaque, protected = _protect_literal_environments(self.snapshot.body)
        stripped = _strip_comments(opaque)
        restored = _restore_protected(stripped, protected)
        return _SUBSUBSECTION_RE.search(restored) is not None

    def referenced_class_and_style_files(self) -> tuple[str, ...]:
        names: list[str] = []
        for match in _CLASS_FILE_RE.finditer(self.snapshot.preamble):
            names.extend(part.strip() for part in match.group(1).split(",") if part.strip())
        for match in _USEPACKAGE_RE.finditer(self.snapshot.preamble):
            names.extend(part.strip() for part in match.group(1).split(",") if part.strip())
        return tuple(dict.fromkeys(names))

    @staticmethod
    def sha256_file(path: Path) -> str:
        return sha256_bytes(path.read_bytes())
