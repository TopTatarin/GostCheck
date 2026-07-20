"""UTF-8 YAML loading, schema validation and include resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import jsonschema  # type: ignore[import-untyped]
import yaml
from pydantic import BaseModel, ValidationError

from normocontrol.errors import ConfigValidationError, LocatedValidationError, RubricValidationError
from normocontrol.rubric.expansion import expand_rubric
from normocontrol.rubric.models import EffectiveRubric, NormocontrolConfig, Rubric


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _yaml_path(parts: Iterable[object]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _read_yaml(path: Path, error_type: type[LocatedValidationError]) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise error_type(str(error), source=str(path)) from error
    try:
        payload = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        location = f"line {mark.line + 1}, column {mark.column + 1}" if mark else "$"
        raise error_type(
            error.problem or "invalid YAML", source=str(path), yaml_path=location
        ) from error
    if not isinstance(payload, dict):
        raise error_type("top-level YAML value must be a mapping", source=str(path))
    return payload


def _schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "schemas" / name


def _validate_schema(
    payload: Mapping[str, Any],
    schema_name: str,
    source: Path,
    error_type: type[LocatedValidationError],
) -> None:
    schema_path = _schema_path(schema_name)
    try:
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        schema = (
            Rubric.model_json_schema()
            if schema_name == "rubric.schema.json"
            else NormocontrolConfig.model_json_schema()
        )
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise error_type(
            f"cannot load schema {schema_path}: {error}", source=str(source)
        ) from error
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        schema_error = errors[0]
        raise error_type(
            schema_error.message,
            source=str(source),
            yaml_path=_yaml_path(schema_error.absolute_path),
        )


def _model_validate[ModelT: BaseModel](
    model: type[ModelT],
    payload: Mapping[str, Any],
    source: Path,
    error_type: type[LocatedValidationError],
) -> ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        detail = error.errors(include_url=False)[0]
        raise error_type(
            str(detail["msg"]), source=str(source), yaml_path=_yaml_path(detail["loc"])
        ) from error


def load_rubric(path: Path | str) -> Rubric:
    """Load and strictly validate one rubric file."""
    source = Path(path)
    payload = _read_yaml(source, RubricValidationError)
    _validate_schema(payload, "rubric.schema.json", source, RubricValidationError)
    rubric = _model_validate(Rubric, payload, source, RubricValidationError)
    # Validate every layer even when no expansion is requested.
    from normocontrol.rubric.expansion import normalize_layer

    for index, rule in enumerate(rubric.rules):
        normalize_layer(rule.layer, yaml_path=f"$.rules[{index}].layer")
    return rubric


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(value, Mapping) and isinstance(existing, Mapping):
            result[key] = _merge(dict(existing), value)
        else:
            result[key] = value
    return result


def _resolve_config(path: Path, chain: tuple[Path, ...]) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved in chain:
        cycle = " -> ".join(str(item) for item in (*chain, resolved))
        raise ConfigValidationError(
            f"cyclic config include: {cycle}", source=str(path), yaml_path="$.include"
        )
    payload = _read_yaml(path, ConfigValidationError)
    include_value = payload.pop("include", ())
    includes = [include_value] if isinstance(include_value, str) else include_value
    if not isinstance(includes, list | tuple):
        raise ConfigValidationError(
            "include must be a path or list of paths", source=str(path), yaml_path="$.include"
        )
    merged: dict[str, Any] = {}
    for index, include in enumerate(includes):
        if not isinstance(include, str):
            raise ConfigValidationError(
                "include entry must be a string",
                source=str(path),
                yaml_path=f"$.include[{index}]",
            )
        merged = _merge(merged, _resolve_config(path.parent / include, (*chain, resolved)))
    return _merge(merged, payload)


def load_config(path: Path | str) -> NormocontrolConfig:
    """Resolve local includes and validate explicit user configuration."""
    source = Path(path)
    payload = _resolve_config(source, ())
    _validate_schema(
        payload,
        "normocontrol-config.schema.json",
        source,
        ConfigValidationError,
    )
    return _model_validate(NormocontrolConfig, payload, source, ConfigValidationError)


def load_effective_rubric(
    rubric_path: Path | str,
    config_path: Path | str,
) -> EffectiveRubric:
    """Load source inputs and produce the effective profile-specific rubric."""
    return expand_rubric(load_rubric(rubric_path), load_config(config_path))
