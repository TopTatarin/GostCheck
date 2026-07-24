"""Load annotated synthetic fixture catalogs for formal evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Expectation = Literal["silent", "fail", "warn", "detect"]


class FixtureSpec(BaseModel):
    """One labeled synthetic fixture."""

    model_config = ConfigDict(extra="forbid")

    id: NonEmptyString
    latex: NonEmptyString | None = None
    pdf: NonEmptyString | None = None
    bib_paths: tuple[NonEmptyString, ...] = ()
    labels: dict[str, Expectation] = Field(default_factory=dict)


class FixtureCatalog(BaseModel):
    """Catalog of annotated fixtures with expected rule outcomes."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    fixtures: tuple[FixtureSpec, ...]


def load_fixture_catalog(path: Path) -> FixtureCatalog:
    """Load and validate a fixture catalog YAML file."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FixtureCatalog.model_validate(payload)


def resolve_fixture_paths(
    spec: FixtureSpec,
    *,
    repo_root: Path,
) -> tuple[Path | None, Path | None, tuple[Path, ...]]:
    """Resolve catalog paths relative to the repository root."""
    latex = repo_root / spec.latex if spec.latex is not None else None
    pdf = repo_root / spec.pdf if spec.pdf is not None else None
    bib_paths = tuple(repo_root / item for item in spec.bib_paths)
    return latex, pdf, bib_paths
