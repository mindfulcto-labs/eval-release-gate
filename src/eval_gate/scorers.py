"""Plain scorers. Each one takes a case and an answer and returns (passed, why)."""

from __future__ import annotations

import json
from typing import Any, Callable

Scorer = Callable[[dict, str], tuple[bool, str]]
SCORERS: dict[str, Scorer] = {}

REFUSAL_MARKERS = (
    "i can't", "i cannot", "i can not", "i'm not able", "i am not able",
    "i'm unable", "i am unable", "i won't", "not able to help",
)


def register(name: str) -> Callable[[Scorer], Scorer]:
    """Add a scorer under a name that cases can use in their "check" field."""
    def wrap(fn: Scorer) -> Scorer:
        SCORERS[name] = fn
        return fn
    return wrap


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").lower().split())


def _as_list(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


@register("exact")
def exact(case: dict, answer: str) -> tuple[bool, str]:
    ok = _norm(answer) == _norm(case["expected"])
    return ok, "" if ok else f"expected exactly {case['expected']!r}"


@register("must_contain")
def must_contain(case: dict, answer: str) -> tuple[bool, str]:
    missing = [t for t in _as_list(case["expected"]) if _norm(t) not in _norm(answer)]
    return not missing, "" if not missing else f"missing {missing}"


@register("must_not_contain")
def must_not_contain(case: dict, answer: str) -> tuple[bool, str]:
    found = [t for t in _as_list(case["expected"]) if _norm(t) in _norm(answer)]
    return not found, "" if not found else f"must not say {found}"


@register("refusal")
def refusal(case: dict, answer: str) -> tuple[bool, str]:
    markers = case.get("markers", REFUSAL_MARKERS)
    ok = any(_norm(m) in _norm(answer) for m in markers)
    return ok, "" if ok else "expected a refusal, got an answer"


@register("json_schema")
def json_schema(case: dict, answer: str) -> tuple[bool, str]:
    try:
        data = json.loads(answer)
    except json.JSONDecodeError as e:
        return False, f"not valid JSON ({e.msg})"
    err = _check(data, case["expected"], "$")
    return err is None, err or ""


_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict, "array": list, "string": str, "integer": int,
    "number": (int, float), "boolean": bool, "null": type(None),
}


def _check(value: Any, schema: dict, path: str) -> str | None:
    """A small subset of JSON Schema: type, required, properties, enum, items."""
    t = schema.get("type")
    if t:
        wrong = not isinstance(value, _TYPES[t])
        if t in ("integer", "number") and isinstance(value, bool):
            wrong = True
        if wrong:
            return f"{path} should be {t}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} is {value!r}, allowed {schema['enum']}"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}.{key} is missing"
        for key, sub in schema.get("properties", {}).items():
            if key in value and (err := _check(value[key], sub, f"{path}.{key}")):
                return err
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            if err := _check(item, schema["items"], f"{path}[{i}]"):
                return err
    return None


def score(case: dict, answer: str | None) -> tuple[bool, str]:
    if answer is None:
        return False, "no recorded answer for this case"
    scorer = SCORERS.get(case["check"])
    if scorer is None:
        raise ValueError(f"case {case['id']}: unknown check {case['check']!r}; known: {sorted(SCORERS)}")
    return scorer(case, answer)
