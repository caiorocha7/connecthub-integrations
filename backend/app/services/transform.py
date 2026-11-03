"""Declarative JSON transformation engine.

Rules are plain data — nothing submitted by users is ever evaluated or executed.

A rule is a list of mappings::

    {"target": "customer.email", "source": "data.customer.email",
     "type": "string", "default": null, "required": true, "transform": "lower"}

or a constant value::

    {"target": "origin", "value": "connecthub"}

Paths use dot notation with optional list indexes: ``data.items[0].sku`` (a leading ``$.`` is
accepted). Supported ``type`` conversions: keep, string, integer, float, boolean, datetime.
Supported ``transform`` operations: lower, upper, trim.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MAX_MAPPINGS = 200
MAX_PATH_DEPTH = 20
_SEGMENT_RE = re.compile(r"^(?P<key>[A-Za-z0-9_\-]+)(?P<idx>(\[\d+\])*)$")
_INDEX_RE = re.compile(r"\[(\d+)\]")

TYPES = {"keep", "string", "integer", "float", "boolean", "datetime"}
TRANSFORMS = {"lower", "upper", "trim"}

_MISSING = object()


class TransformError(ValueError):
    """Raised when a payload cannot be transformed according to a rule."""


class RuleValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


PathToken = str | int


def parse_path(path: str) -> list[PathToken]:
    if not isinstance(path, str) or not path.strip():
        raise RuleValidationError(["caminho vazio"])
    raw = path.strip()
    if raw.startswith("$."):
        raw = raw[2:]
    elif raw == "$":
        return []
    tokens: list[PathToken] = []
    for segment in raw.split("."):
        match = _SEGMENT_RE.match(segment)
        if not match:
            raise RuleValidationError([f"segmento de caminho inválido: '{segment}' em '{path}'"])
        tokens.append(match.group("key"))
        tokens.extend(int(i) for i in _INDEX_RE.findall(match.group("idx")))
    if len(tokens) > MAX_PATH_DEPTH:
        raise RuleValidationError([f"caminho muito profundo: '{path}'"])
    return tokens


def get_path(data: Any, tokens: list[PathToken]) -> Any:
    current = data
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return _MISSING
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                return _MISSING
            current = current[token]
    return current


def set_path(data: dict[str, Any], tokens: list[PathToken], value: Any) -> None:
    if not tokens:
        raise TransformError("o destino não pode ser a raiz do documento")
    current: Any = data
    for i, token in enumerate(tokens):
        last = i == len(tokens) - 1
        nxt = None if last else tokens[i + 1]
        if isinstance(token, int):
            if not isinstance(current, list):
                raise TransformError("conflito de tipos ao montar o destino")
            while len(current) <= token:
                current.append(None)
            if last:
                current[token] = value
            else:
                if current[token] is None:
                    current[token] = [] if isinstance(nxt, int) else {}
                current = current[token]
        else:
            if not isinstance(current, dict):
                raise TransformError("conflito de tipos ao montar o destino")
            if last:
                current[token] = value
            else:
                if not isinstance(current.get(token), dict | list):
                    current[token] = [] if isinstance(nxt, int) else {}
                current = current[token]


def _convert(value: Any, type_name: str, target: str) -> Any:
    if value is None or type_name == "keep":
        return value
    try:
        if type_name == "string":
            return value if isinstance(value, str) else str(value)
        if type_name == "integer":
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            return int(str(value).strip()) if isinstance(value, str) else int(value)
        if type_name == "float":
            if isinstance(value, bool):
                raise ValueError
            return float(value)
        if type_name == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, int | float):
                return value != 0
            lowered = str(value).strip().lower()
            if lowered in {"true", "1", "yes", "sim", "y", "s"}:
                return True
            if lowered in {"false", "0", "no", "nao", "não", "n"}:
                return False
            raise ValueError
        if type_name == "datetime":
            if isinstance(value, int | float) and not isinstance(value, bool):
                return datetime.fromtimestamp(value, tz=UTC).isoformat()
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.isoformat()
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise TransformError(
            f"não foi possível converter '{target}' para {type_name}: valor {value!r}"
        ) from exc
    raise TransformError(f"tipo desconhecido: {type_name}")


def _apply_string_transform(value: Any, op: str | None) -> Any:
    if op is None or not isinstance(value, str):
        return value
    if op == "lower":
        return value.lower()
    if op == "upper":
        return value.upper()
    if op == "trim":
        return value.strip()
    return value


@dataclass
class CompiledMapping:
    target: list[PathToken]
    target_raw: str
    source: list[PathToken] | None
    has_value: bool
    value: Any
    has_default: bool
    default: Any
    type_name: str
    required: bool
    transform: str | None


@dataclass
class CompiledRule:
    include_unmapped: bool
    mappings: list[CompiledMapping] = field(default_factory=list)


def compile_rule(mappings: list[dict[str, Any]], include_unmapped: bool = False) -> CompiledRule:
    """Validate the rule and return a compiled representation. Raises RuleValidationError."""
    errors: list[str] = []
    if not isinstance(mappings, list):
        raise RuleValidationError(["'mappings' deve ser uma lista"])
    if len(mappings) > MAX_MAPPINGS:
        raise RuleValidationError([f"máximo de {MAX_MAPPINGS} mapeamentos"])
    compiled: list[CompiledMapping] = []
    targets: set[str] = set()
    for i, m in enumerate(mappings, start=1):
        prefix = f"mapeamento #{i}"
        if not isinstance(m, dict):
            errors.append(f"{prefix}: deve ser um objeto")
            continue
        target_raw = m.get("target")
        source_raw = m.get("source")
        has_value = "value" in m and m.get("value") is not None and not source_raw
        try:
            target = parse_path(str(target_raw or ""))
            if not target:
                raise RuleValidationError(["o destino não pode ser a raiz"])
        except RuleValidationError as exc:
            errors.append(f"{prefix}: destino inválido ({exc})")
            continue
        if target_raw in targets:
            errors.append(f"{prefix}: destino '{target_raw}' duplicado")
        targets.add(str(target_raw))
        source: list[PathToken] | None = None
        if source_raw:
            try:
                source = parse_path(str(source_raw))
            except RuleValidationError as exc:
                errors.append(f"{prefix}: origem inválida ({exc})")
                continue
        elif not has_value:
            errors.append(f"{prefix}: informe 'source' (caminho de origem) ou 'value' (constante)")
            continue
        type_name = m.get("type") or "keep"
        if type_name not in TYPES:
            errors.append(f"{prefix}: tipo '{type_name}' não suportado")
        op = m.get("transform") or None
        if op is not None and op not in TRANSFORMS:
            errors.append(f"{prefix}: transformação '{op}' não suportada")
        compiled.append(
            CompiledMapping(
                target=target,
                target_raw=str(target_raw),
                source=source,
                has_value=has_value,
                value=m.get("value"),
                has_default="default" in m and m.get("default") is not None,
                default=m.get("default"),
                type_name=type_name,
                required=bool(m.get("required", False)),
                transform=op,
            )
        )
    if errors:
        raise RuleValidationError(errors)
    return CompiledRule(include_unmapped=include_unmapped, mappings=compiled)


def apply_rule(rule: CompiledRule, payload: Any) -> Any:
    """Apply a compiled rule to a payload, returning a new document."""
    if not rule.mappings:
        return copy.deepcopy(payload)
    if rule.include_unmapped and isinstance(payload, dict):
        output: dict[str, Any] = copy.deepcopy(payload)
    else:
        output = {}
    for m in rule.mappings:
        if m.source is not None:
            value = get_path(payload, m.source)
        else:
            value = copy.deepcopy(m.value)
        if value is _MISSING or value is None:
            if m.has_default:
                value = copy.deepcopy(m.default)
            elif m.required:
                raise TransformError(f"campo obrigatório ausente para '{m.target_raw}'")
            else:
                continue
        value = _apply_string_transform(value, m.transform)
        value = _convert(value, m.type_name, m.target_raw)
        set_path(output, m.target, value)
    return output


def transform_payload(mappings: list[dict[str, Any]], include_unmapped: bool, payload: Any) -> Any:
    return apply_rule(compile_rule(mappings, include_unmapped), payload)


def extract_value(payload: Any, path: str) -> Any | None:
    try:
        value = get_path(payload, parse_path(path))
    except RuleValidationError:
        return None
    return None if value is _MISSING else value
