"""Safe recursive extraction of multi-file LaTeX projects."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from pylatexenc.latex2text import LatexNodes2Text  # type: ignore[import-untyped]
from pylatexenc.latexwalker import LatexMacroNode, LatexWalker  # type: ignore[import-untyped]

from normocontrol.extract.base import (
    DocumentBundle,
    DocumentExtractor,
    ExtractedDocument,
    ExtractionError,
    ExtractionQuality,
    HeadingCandidate,
    IncludeCycleError,
    IncludeNotFoundError,
    SourceFile,
    SourceFormat,
    SourceNotFoundError,
    UnsafePathError,
    safe_relative_path,
    sha256_bytes,
    sha256_text,
)
from normocontrol.extract.chunking import Chunker
from normocontrol.extract.sections import SectionDetector

_INCLUDE_RE = re.compile(
    r"\\(?P<command>input|include)\s*(?:\{(?P<braced>[^{}]+)\}|(?P<bare>[^\s{}%]+))"
)
_BIBLIOGRAPHY_RE = re.compile(
    r"\\(?P<command>addbibresource|bibliography)\s*"
    r"(?:\[[^\]]*\]\s*)?\{(?P<value>[^{}]*)\}",
    re.IGNORECASE,
)
_PROTECTED_BEGIN_RE = re.compile(r"\\begin\{(verbatim\*?|Verbatim|lstlisting|minted)\}")
_SECTION_LEVELS = {"chapter": 1, "section": 2, "subsection": 3, "subsubsection": 4}


def _protect_literal_environments(text: str) -> tuple[str, dict[str, str]]:
    """Replace literal environments with opaque placeholders before parsing directives."""
    protected: dict[str, str] = {}
    output: list[str] = []
    cursor = 0
    while match := _PROTECTED_BEGIN_RE.search(text, cursor):
        output.append(text[cursor : match.start()])
        environment = match.group(1)
        token_re = re.compile(rf"\\(?P<action>begin|end)\{{{re.escape(environment)}\}}")
        depth = 1
        end = match.end()
        while depth:
            token = token_re.search(text, end)
            if token is None:
                # An unterminated literal block is still protected through end-of-file.
                end = len(text)
                break
            depth += 1 if token.group("action") == "begin" else -1
            end = token.end()
        literal = text[match.start() : end]
        placeholder = f"\\NCprotected{{{len(protected)}}}"
        protected[placeholder] = literal
        output.append(placeholder)
        cursor = end
    output.append(text[cursor:])
    return "".join(output), protected


def _strip_comments(text: str) -> str:
    """Remove LaTeX comments while retaining escaped percent signs and newlines."""
    result: list[str] = []
    for line in text.splitlines(keepends=True):
        comment_at: int | None = None
        for index, character in enumerate(line):
            if character != "%":
                continue
            slash_count = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                slash_count += 1
                cursor -= 1
            if slash_count % 2 == 0:
                comment_at = index
                break
        if comment_at is None:
            result.append(line)
            continue
        newline = "\n" if line.endswith("\n") else ""
        result.append(line[:comment_at].rstrip("\r\n") + newline)
    return "".join(result)


def _restore_protected(text: str, protected: dict[str, str]) -> str:
    for placeholder, literal in protected.items():
        text = text.replace(placeholder, literal)
    return text


def _normalize_plain_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _to_plain_text(expanded: str) -> str:
    """Convert markup while restoring literal bodies after the LaTeX AST walk."""
    opaque, protected = _protect_literal_environments(expanded)
    literal_tokens: dict[str, str] = {}
    for index, (placeholder, environment) in enumerate(protected.items()):
        token = f"NCVERBATIMTOKEN{index}"
        opaque = opaque.replace(placeholder, token)
        begin_end = re.match(r"\\begin\{[^{}]+\}", environment)
        closing = re.search(r"\\end\{[^{}]+\}\s*$", environment)
        body_start = begin_end.end() if begin_end is not None else 0
        body_end = closing.start() if closing is not None else len(environment)
        literal_tokens[token] = environment[body_start:body_end]
    plain = cast(str, LatexNodes2Text().latex_to_text(opaque))
    for token, literal in literal_tokens.items():
        plain = plain.replace(token, literal)
    return plain


def _walk_nodes(nodes: list[Any]) -> list[Any]:
    result: list[Any] = []
    for node in nodes:
        result.append(node)
        children = getattr(node, "nodelist", None)
        if isinstance(children, list):
            result.extend(_walk_nodes(children))
        nodeargd = getattr(node, "nodeargd", None)
        arguments = getattr(nodeargd, "argnlist", None)
        if isinstance(arguments, list):
            for argument in arguments:
                nested = getattr(argument, "nodelist", None)
                if isinstance(nested, list):
                    result.extend(_walk_nodes(nested))
    return result


def _locate_title(text: str, title: str, cursor: int) -> int:
    words = [re.escape(word) for word in title.split()]
    if words:
        match = re.search(r"\s+".join(words), text[cursor:], flags=re.IGNORECASE)
        if match is not None:
            return cursor + match.start()
    return cursor


def _latex_headings(expanded: str, plain_text: str) -> tuple[HeadingCandidate, ...]:
    converter = LatexNodes2Text()
    headings: list[HeadingCandidate] = []
    cursor = 0
    try:
        nodes, _, _ = LatexWalker(expanded).get_latex_nodes()
    except Exception:  # pylatexenc exposes several parser exception types across minor versions
        nodes = []
    for node in _walk_nodes(nodes):
        if not isinstance(node, LatexMacroNode) or node.macroname not in _SECTION_LEVELS:
            continue
        arguments = getattr(getattr(node, "nodeargd", None), "argnlist", None)
        if not isinstance(arguments, list):
            continue
        mandatory = next(
            (argument for argument in reversed(arguments) if argument is not None), None
        )
        if mandatory is None:
            continue
        title = _normalize_plain_text(converter.nodelist_to_text([mandatory]))
        if not title:
            continue
        position = _locate_title(plain_text, title, cursor)
        cursor = position + len(title)
        headings.append(
            HeadingCandidate(
                title=title,
                level=_SECTION_LEVELS[node.macroname],
                char_start=position,
                origin="latex_ast",
            )
        )
    return tuple(headings)


class LatexExtractor(DocumentExtractor):
    """Expand safe local includes and convert LaTeX AST to normalized text."""

    def __init__(self, project_root: Path, *, token_budget: int = 800) -> None:
        try:
            self.project_root = project_root.resolve(strict=True)
        except FileNotFoundError as error:
            raise SourceNotFoundError(f"project root not found: {project_root.name}") from error
        self.chunker = Chunker(token_budget=token_budget)
        self._source_files: list[SourceFile] = []
        self._seen_metadata: set[Path] = set()

    def extract(self, source: Path) -> DocumentBundle:
        """Extract a main TeX file and every reachable local include."""
        self._source_files = []
        self._seen_metadata = set()
        main = self._resolve_source(source, base=self.project_root, included=False)
        expanded = self._expand_file(main, stack=())
        try:
            plain = _to_plain_text(expanded)
        except Exception as error:
            raise ExtractionError("unable to decode LaTeX source") from error
        text = _normalize_plain_text(plain)
        document = ExtractedDocument(
            source_format=SourceFormat.LATEX,
            source_hash=sha256_text(text),
            text=text,
            extraction_quality=ExtractionQuality.HIGH,
            source_files=tuple(self._source_files),
            headings=_latex_headings(expanded, text),
        )
        sections = SectionDetector().detect(document)
        chunks = self.chunker.chunk(document, sections)
        return DocumentBundle(
            source_format=document.source_format,
            source_hash=document.source_hash,
            text=document.text,
            extraction_quality=document.extraction_quality,
            source_files=document.source_files,
            sections=sections,
            chunks=chunks,
        )

    def discover_bibliography_paths(self, source: Path) -> tuple[Path, ...]:
        """Resolve bibliography resources without crossing ``project_root``."""
        main = self._resolve_source(source, base=self.project_root, included=False)
        references = self._bibliography_references(main, visited=frozenset())
        if references:
            paths = [
                path
                for reference in references
                if (path := self._resolve_bibliography(reference)) is not None
            ]
        else:
            paths = [path for path in self.project_files() if path.suffix.casefold() == ".bib"]
        return self._stable_unique_paths(paths)

    def bibliography_declared(self, source: Path) -> bool:
        """Return whether reachable LaTeX declares a bibliography command."""
        main = self._resolve_source(source, base=self.project_root, included=False)
        return bool(self._bibliography_references(main, visited=frozenset()))

    def project_files(self, *, excluded_roots: tuple[Path, ...] = ()) -> tuple[Path, ...]:
        """Return every safe project file in deterministic portable order."""
        excluded = tuple(
            resolved
            for root in excluded_roots
            if (resolved := root.resolve(strict=False)).is_relative_to(self.project_root)
        )
        pending = [self.project_root]
        visited: set[Path] = set()
        files: list[Path] = []
        while pending:
            directory = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            entries = sorted(directory.iterdir(), key=self._path_sort_key, reverse=True)
            for entry in entries:
                try:
                    resolved = entry.resolve(strict=True)
                except FileNotFoundError as error:
                    raise SourceNotFoundError(f"project entry not found: {entry.name}") from error
                if not resolved.is_relative_to(self.project_root):
                    raise UnsafePathError(
                        f"project entry resolves outside project root: {entry.name}"
                    )
                if any(
                    resolved == excluded_root or resolved.is_relative_to(excluded_root)
                    for excluded_root in excluded
                ):
                    continue
                if resolved.is_dir():
                    pending.append(resolved)
                elif resolved.is_file():
                    files.append(resolved)
        return self._stable_unique_paths(files)

    def _resolve_source(self, source: Path, *, base: Path, included: bool) -> Path:
        candidate = source if source.is_absolute() or source.exists() else base / source
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".tex")
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as error:
            error_type = IncludeNotFoundError if included else SourceNotFoundError
            raise error_type(f"LaTeX source not found: {source.name}") from error
        if not resolved.is_relative_to(self.project_root):
            raise UnsafePathError(f"LaTeX source resolves outside project root: {source.name}")
        if not resolved.is_file():
            raise SourceNotFoundError(f"LaTeX source is not a file: {source.name}")
        return resolved

    def _bibliography_references(
        self,
        path: Path,
        *,
        visited: frozenset[Path],
    ) -> tuple[str, ...]:
        if path in visited:
            return ()
        payload = path.read_bytes()
        try:
            raw = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ExtractionError(f"LaTeX source is not UTF-8: {path.name}") from error
        opaque, _protected = _protect_literal_environments(raw)
        stripped = _strip_comments(opaque)
        references: list[str] = []
        for match in _BIBLIOGRAPHY_RE.finditer(stripped):
            value = match.group("value")
            if match.group("command").casefold() == "bibliography":
                references.extend(part.strip() for part in value.split(",") if part.strip())
            elif value.strip():
                references.append(value.strip())
        for match in _INCLUDE_RE.finditer(stripped):
            include_name = (match.group("braced") or match.group("bare")).strip()
            child = self._resolve_source(Path(include_name), base=path.parent, included=True)
            references.extend(
                self._bibliography_references(child, visited=visited | frozenset({path}))
            )
        return tuple(references)

    def _resolve_bibliography(self, reference: str) -> Path | None:
        portable = reference.strip().replace("\\", "/")
        posix = PurePosixPath(portable)
        windows = PureWindowsPath(reference.strip())
        display_name = posix.name or "bibliography"
        if not portable or posix.is_absolute() or windows.is_absolute() or bool(windows.drive):
            raise UnsafePathError(f"bibliography path must be relative: {display_name}")
        if ".." in posix.parts:
            raise UnsafePathError(f"bibliography path traversal is not allowed: {display_name}")
        candidate = self.project_root.joinpath(*posix.parts)
        if candidate.suffix == "":
            candidate = candidate.with_suffix(".bib")
        elif candidate.suffix.casefold() != ".bib":
            return None
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None
        if not resolved.is_relative_to(self.project_root):
            raise UnsafePathError(f"bibliography resolves outside project root: {display_name}")
        if not resolved.is_file():
            return None
        return resolved

    def _stable_unique_paths(self, paths: list[Path]) -> tuple[Path, ...]:
        unique: dict[str, Path] = {}
        for path in paths:
            relative = path.relative_to(self.project_root).as_posix()
            key = unicodedata.normalize("NFC", relative).casefold()
            unique.setdefault(key, path)
        return tuple(
            unique[key]
            for key in sorted(
                unique,
                key=lambda item: (item, unique[item].relative_to(self.project_root).as_posix()),
            )
        )

    def _path_sort_key(self, path: Path) -> tuple[str, str]:
        relative = path.relative_to(self.project_root).as_posix()
        return unicodedata.normalize("NFC", relative).casefold(), relative

    def _expand_file(self, path: Path, *, stack: tuple[Path, ...]) -> str:
        if path in stack:
            chain = " -> ".join(item.name for item in (*stack, path))
            raise IncludeCycleError(f"cyclic LaTeX include: {chain}")
        payload = path.read_bytes()
        try:
            raw = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ExtractionError(f"LaTeX source is not UTF-8: {path.name}") from error
        if path not in self._seen_metadata:
            self._seen_metadata.add(path)
            self._source_files.append(
                SourceFile(
                    path=safe_relative_path(path, self.project_root),
                    sha256=sha256_bytes(payload),
                )
            )
        opaque, protected = _protect_literal_environments(raw)
        stripped = _strip_comments(opaque)
        output: list[str] = []
        cursor = 0
        for match in _INCLUDE_RE.finditer(stripped):
            output.append(stripped[cursor : match.start()])
            include_name = (match.group("braced") or match.group("bare")).strip()
            child = self._resolve_source(Path(include_name), base=path.parent, included=True)
            output.append(self._expand_file(child, stack=(*stack, path)))
            cursor = match.end()
        output.append(stripped[cursor:])
        return _restore_protected("".join(output), protected)
