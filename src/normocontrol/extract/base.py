"""Public contracts and shared helpers for safe document extraction."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from normocontrol.errors import NormocontrolError

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ExtractionError(NormocontrolError):
    """Base class for expected extraction failures."""


class UnsafePathError(ExtractionError):
    """Raised when a source resolves outside its declared project root."""


class SourceNotFoundError(ExtractionError):
    """Raised when an input document or included source does not exist."""


class IncludeNotFoundError(SourceNotFoundError):
    """Raised when a referenced LaTeX source does not exist."""


class IncludeCycleError(ExtractionError):
    """Raised for a recursive LaTeX include chain."""


class PdfExtractionError(ExtractionError):
    """Raised when a PDF is corrupt or cannot be decoded."""


class PdfEncryptedError(PdfExtractionError):
    """Raised when a PDF needs a password."""


class SourceFormat(StrEnum):
    """Supported source representations."""

    LATEX = "latex"
    PDF = "pdf"


class ExtractionQuality(StrEnum):
    """Reliability of the available machine-readable text layer."""

    HIGH = "high"
    DEGRADED = "degraded"


class SectionKind(StrEnum):
    """Semantic section aliases used by downstream advisory checks."""

    DOCUMENT = "document"
    ANNOTATION = "annotation"
    INTRODUCTION = "introduction"
    CONCLUSION = "conclusion"
    APPENDIX = "appendix"
    OTHER = "other"


class ContractModel(BaseModel):
    """Strict immutable base for serialized extraction contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundingBox(ContractModel):
    """PDF coordinates in points; zero-area boxes are retained as degraded evidence."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        values = (self.x0, self.y0, self.x1, self.y1)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bounding box coordinates must be finite")
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box coordinates must be ordered")
        return self


class TextSpan(ContractModel):
    """Addressable PDF text span with typography and full-text offsets."""

    text: str = Field(repr=False)
    page: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    font: str | None = None
    font_size: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    bbox: BoundingBox

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.char_end < self.char_start:
            raise ValueError("span char_end must not precede char_start")
        if self.char_end - self.char_start != len(self.text):
            raise ValueError("span offsets must match text length")
        return self


class PageInfo(ContractModel):
    """Geometry retained for layout-sensitive formal rules."""

    number: int = Field(ge=1)
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    rotation: int


class HeadingCandidate(ContractModel):
    """A structural heading discovered from AST, outline, or PDF typography."""

    title: NonEmptyString
    level: int = Field(ge=1)
    char_start: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    origin: NonEmptyString


class SourceFile(ContractModel):
    """Safe metadata for one source file; contents are intentionally excluded."""

    path: NonEmptyString
    sha256: str

    @model_validator(mode="after")
    def validate_sha256(self) -> Self:
        if SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must contain 64 lowercase hexadecimal characters")
        return self


class ExtractedDocument(ContractModel):
    """Normalized intermediate document consumed by sectioning and chunking."""

    source_format: SourceFormat
    source_hash: str
    text: str = Field(repr=False)
    extraction_quality: ExtractionQuality
    source_files: tuple[SourceFile, ...]
    spans: tuple[TextSpan, ...] = ()
    pages: tuple[PageInfo, ...] = ()
    headings: tuple[HeadingCandidate, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        if SHA256_RE.fullmatch(self.source_hash) is None:
            raise ValueError("source_hash must be a SHA-256 digest")
        if not self.source_files:
            raise ValueError("source_files must not be empty")
        for span in self.spans:
            if span.char_end > len(self.text):
                raise ValueError("span lies outside extracted text")
        return self


class Section(ContractModel):
    """A hierarchical, addressable slice of normalized text."""

    section_id: NonEmptyString
    title: NonEmptyString
    kind: SectionKind
    level: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    locator: NonEmptyString

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.char_end < self.char_start:
            raise ValueError("section char_end must not precede char_start")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("section page range must be ordered")
        return self


class ResolvedQuote(ContractModel):
    """A deliberately bounded excerpt returned only on explicit resolution."""

    locator: NonEmptyString
    text: str = Field(repr=False)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)


class DocumentChunk(ContractModel):
    """Token-bounded section chunk with provenance and overlap metadata."""

    chunk_id: NonEmptyString
    text: str = Field(repr=False)
    token_count: int = Field(ge=0)
    source_hash: str
    section_id: NonEmptyString
    char_start: int = Field(ge=0)
    content_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    overlap_chars: int = Field(ge=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    quote_locator: NonEmptyString

    @model_validator(mode="after")
    def validate_chunk(self) -> Self:
        if SHA256_RE.fullmatch(self.source_hash) is None:
            raise ValueError("source_hash must be a SHA-256 digest")
        if not self.char_start <= self.content_start <= self.char_end:
            raise ValueError("chunk offsets must be ordered")
        if self.overlap_chars != self.content_start - self.char_start:
            raise ValueError("overlap_chars must match chunk offsets")
        if len(self.text) != self.char_end - self.char_start:
            raise ValueError("chunk text length must match offsets")
        expected = make_locator(self.source_hash, self.char_start, self.char_end)
        if self.quote_locator != expected:
            raise ValueError("quote_locator does not match chunk provenance")
        return self

    def resolve_quote(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        max_chars: int = 400,
    ) -> ResolvedQuote:
        """Resolve a chunk-relative quote while enforcing a hard disclosure bound."""
        relative_end = len(self.text) if end is None else end
        if start < 0 or relative_end < start or relative_end > len(self.text):
            raise ValueError("quote range lies outside chunk")
        if max_chars < 1 or relative_end - start > max_chars:
            raise ValueError("quote exceeds configured disclosure limit")
        absolute_start = self.char_start + start
        absolute_end = self.char_start + relative_end
        return ResolvedQuote(
            locator=make_locator(self.source_hash, absolute_start, absolute_end),
            text=self.text[start:relative_end],
            page_start=self.page_start,
            page_end=self.page_end,
        )


class DocumentBundle(ContractModel):
    """Canonical extraction result shared by deterministic and advisory stages."""

    schema_version: str = "1.0"
    source_format: SourceFormat
    source_hash: str
    text: str = Field(repr=False)
    extraction_quality: ExtractionQuality
    source_files: tuple[SourceFile, ...]
    spans: tuple[TextSpan, ...] = ()
    pages: tuple[PageInfo, ...] = ()
    sections: tuple[Section, ...]
    chunks: tuple[DocumentChunk, ...]
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if SHA256_RE.fullmatch(self.source_hash) is None:
            raise ValueError("source_hash must be a SHA-256 digest")
        for section in self.sections:
            if section.char_end > len(self.text):
                raise ValueError("section lies outside bundle text")
        for chunk in self.chunks:
            if chunk.source_hash != self.source_hash or chunk.char_end > len(self.text):
                raise ValueError("chunk provenance does not match bundle")
            if self.text[chunk.char_start : chunk.char_end] != chunk.text:
                raise ValueError("chunk text does not match bundle text")
        return self

    def resolve_quote(
        self,
        locator: str,
        *,
        max_chars: int = 400,
    ) -> ResolvedQuote:
        """Resolve only a locator wholly contained in a published chunk."""
        source_hash, start, end = parse_locator(locator)
        if source_hash != self.source_hash:
            raise ValueError("quote locator belongs to a different source")
        if max_chars < 1 or end - start > max_chars:
            raise ValueError("quote exceeds configured disclosure limit")
        owner = next(
            (chunk for chunk in self.chunks if chunk.char_start <= start <= end <= chunk.char_end),
            None,
        )
        if owner is None:
            raise ValueError("quote locator lies outside published chunks")
        return ResolvedQuote(
            locator=locator,
            text=self.text[start:end],
            page_start=owner.page_start,
            page_end=owner.page_end,
        )


class DocumentExtractor(ABC):
    """Typed interface implemented by all source extractors."""

    @abstractmethod
    def extract(self, source: Path) -> DocumentBundle:
        """Extract one source into the canonical bundle."""


def sha256_bytes(payload: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    """Hash normalized UTF-8 text used by all locators."""
    return sha256_bytes(text.encode("utf-8"))


def make_locator(source_hash: str, start: int, end: int) -> str:
    """Create a path-free evidence locator."""
    return f"sha256:{source_hash}:{start}-{end}"


def parse_locator(locator: str) -> tuple[str, int, int]:
    """Parse and validate an evidence locator without exposing document text."""
    match = re.fullmatch(r"sha256:([0-9a-f]{64}):(\d+)-(\d+)", locator)
    if match is None:
        raise ValueError("invalid quote locator")
    start, end = int(match.group(2)), int(match.group(3))
    if end < start:
        raise ValueError("quote locator range is reversed")
    return match.group(1), start, end


def safe_relative_path(path: Path, project_root: Path) -> str:
    """Return a portable relative display path after a containment check."""
    resolved_root = project_root.resolve(strict=True)
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise SourceNotFoundError(f"source file not found: {path.name}") from error
    if not resolved.is_relative_to(resolved_root):
        raise UnsafePathError(f"source resolves outside project root: {path.name}")
    return resolved.relative_to(resolved_root).as_posix()
