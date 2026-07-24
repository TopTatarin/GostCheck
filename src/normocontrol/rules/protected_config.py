"""Load protected class and preamble policy for SYS rules."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256String = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ProtectedConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProtectedClassFile(ProtectedConfigModel):
    path: NonEmptyString
    sha256: Sha256String


class ForbiddenPattern(ProtectedConfigModel):
    pattern: NonEmptyString
    message: NonEmptyString


class ProtectedFilesConfig(ProtectedConfigModel):
    """Reference hashes and preamble restrictions for formal SYS rules."""

    version: int = Field(ge=1)
    class_files: tuple[ProtectedClassFile, ...] = ()
    forbidden_preamble: tuple[ForbiddenPattern, ...] = ()
    allowed_renewcommand: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def validate_unique_paths(self) -> Self:
        paths = [item.path for item in self.class_files]
        if len(set(paths)) != len(paths):
            raise ValueError("class_files paths must be unique")
        return self


def load_protected_files_config(path: Path) -> ProtectedFilesConfig | None:
    """Load protected-files YAML or return ``None`` when the file is absent."""
    if not path.is_file():
        return None
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("protected files config must be a mapping")
    return ProtectedFilesConfig.model_validate(payload)


def default_protected_config_path(project_root: Path) -> Path:
    """Return the conventional protected-files path inside a LaTeX project."""
    return project_root / "protected-files.yaml"
