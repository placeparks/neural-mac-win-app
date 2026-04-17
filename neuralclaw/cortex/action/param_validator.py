"""
Tool Parameter Validator — Framework-level argument validation and coercion.

Validates incoming tool arguments against the tool's JSON Schema *before*
the handler runs.  Where unambiguous, coerces types (e.g. string "42" →
int 42) rather than rejecting outright — LLMs frequently serialize
numbers as strings.

No external dependencies; handles the 6 JSON Schema types that
ToolParameter uses: string, integer, number, boolean, array, object.
"""

from __future__ import annotations

from typing import Any

from neuralclaw.errors import ErrorCode, StructuredError


def validate_tool_params(
    tool_name: str,
    args: dict[str, Any],
    schema: dict[str, Any],
) -> StructuredError | None:
    """
    Validate and coerce *args* against a JSON Schema dict.

    Mutates *args* in-place when coercion succeeds (so the handler receives
    correctly-typed values).

    Returns ``None`` if valid, or a :class:`StructuredError` describing the
    first validation failure.
    """
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    # 1. Required field check
    missing = [r for r in required if r not in args]
    if missing:
        return StructuredError(
            code=ErrorCode.TOOL_INVALID_PARAMS,
            message=f"Missing required parameter(s): {', '.join(missing)}",
            recoverable=True,
            suggestion=f"Provide the required parameters: {', '.join(missing)}",
            details={"missing": missing},
        )

    # 2. Type validation + coercion for each provided arg
    for key, value in list(args.items()):
        prop_schema = properties.get(key)
        if prop_schema is None:
            continue  # Extra args are allowed (additionalProperties not restricted)

        expected_type = prop_schema.get("type")
        if expected_type is None:
            continue

        coerced = _coerce(value, expected_type)
        if coerced is _INVALID:
            return StructuredError(
                code=ErrorCode.TOOL_INVALID_PARAMS,
                message=f"Parameter '{key}' expected type '{expected_type}', got {type(value).__name__}: {str(value)[:100]}",
                recoverable=True,
                suggestion=f"Pass '{key}' as {expected_type}.",
            )
        args[key] = coerced  # Apply coercion in-place

        # 3. Enum validation
        enum_values = prop_schema.get("enum")
        if enum_values is not None and coerced not in enum_values:
            return StructuredError(
                code=ErrorCode.TOOL_INVALID_PARAMS,
                message=f"Parameter '{key}' must be one of {enum_values}, got '{coerced}'",
                recoverable=True,
                suggestion=f"Use one of: {', '.join(str(v) for v in enum_values)}",
            )

    return None


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

_INVALID = object()  # Sentinel for failed coercion


def _coerce(value: Any, expected: str) -> Any:
    """
    Attempt to coerce *value* to *expected* JSON Schema type.

    Returns the coerced value on success, or ``_INVALID`` on failure.
    """
    if expected == "string":
        if isinstance(value, str):
            return value
        # Allow numbers/bools → string
        if isinstance(value, (int, float, bool)):
            return str(value)
        return _INVALID

    if expected == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except (ValueError, OverflowError):
                return _INVALID
        if isinstance(value, float) and value == int(value):
            return int(value)
        return _INVALID

    if expected == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if isinstance(value, str):
            try:
                return float(value)
            except (ValueError, OverflowError):
                return _INVALID
        return _INVALID

    if expected == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            low = value.lower()
            if low in ("true", "1", "yes"):
                return True
            if low in ("false", "0", "no"):
                return False
            return _INVALID
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        return _INVALID

    if expected == "array":
        if isinstance(value, list):
            return value
        return _INVALID

    if expected == "object":
        if isinstance(value, dict):
            return value
        return _INVALID

    # Unknown type — pass through
    return value
