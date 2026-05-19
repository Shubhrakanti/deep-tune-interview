"""Normalized JSON-match grader.

Pulls the last `{...}` block out of the agent's final assistant text, parses
it, normalizes it, and compares it to `task["answer"]` (which is itself JSON
inside tasks.json).

Normalization rules:
  - strings: stripped + lowercased
  - floats: rounded to 2 decimal places (tasks.json answers carry at most 2 dp)
  - lists: sorted (so order doesn't matter for "list[str]" answers like
    problem9). For dicts with multiple equal-length list values (e.g.
    `{product_titles: [...], ratings: [...]}` in problem1), we treat them as
    parallel arrays and compare the unordered set of tuples — preserving the
    pairing across keys while ignoring row order.
"""

from __future__ import annotations

import json
import re
from typing import Any

from grading.base import GradeResult, Grader


def extract_json(text: str) -> Any:
    """Find the last top-level JSON object in `text` and return the parsed value.

    Raises ValueError if nothing parseable is found.
    """
    if not text:
        raise ValueError("empty agent output")

    # Strip markdown fences if present (```json ... ```).
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.replace("```", "")

    # Find every top-level {...} substring by scanning for balanced braces, then
    # try parsing them from last to first.
    candidates: list[str] = []
    depth = 0
    start = -1
    for i, ch in enumerate(cleaned):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidates.append(cleaned[start : i + 1])
                start = -1

    for cand in reversed(candidates):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue

    raise ValueError(f"no parseable JSON object in agent output:\n{text!r}")


def _normalize_value(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, int):
        return v
    return v


def _normalize(obj: Any) -> Any:
    """Recursively normalize. Parallel-list dicts get converted into a sorted
    list of tuples so pairing is preserved but row order is not."""
    if isinstance(obj, dict):
        list_keys = [k for k, v in obj.items() if isinstance(v, list)]
        if len(list_keys) >= 2:
            lengths = {len(obj[k]) for k in list_keys}
            if len(lengths) == 1 and lengths.pop() > 0:
                # Parallel arrays: bind by row, sort by row.
                sorted_keys = sorted(list_keys)
                rows = []
                for i in range(len(obj[sorted_keys[0]])):
                    rows.append(
                        tuple(_normalize_value(obj[k][i]) for k in sorted_keys)
                    )
                paired = {
                    "__parallel__": (tuple(sorted_keys), sorted(rows)),
                }
                for k, v in obj.items():
                    if k not in list_keys:
                        paired[k] = _normalize(v)
                return paired
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        items = [_normalize(x) for x in obj]
        # Sort primitives directly; otherwise compare by repr so nested dicts
        # also become order-insensitive.
        try:
            return sorted(items)
        except TypeError:
            return sorted(items, key=repr)
    return _normalize_value(obj)


class JsonMatchGrader(Grader):
    """Compare extracted-from-agent JSON against task['answer'] (also JSON)."""

    def grade(self, task: dict, agent_output: str) -> GradeResult:
        try:
            expected = json.loads(task["answer"])
        except (KeyError, json.JSONDecodeError) as e:
            return GradeResult(
                passed=False,
                message=f"task['answer'] is not valid JSON: {e}",
                details={"task_id": task.get("id")},
            )

        try:
            actual = extract_json(agent_output)
        except ValueError as e:
            return GradeResult(
                passed=False,
                message=f"could not parse JSON from agent output: {e}",
                details={
                    "expected": expected,
                    "agent_output_preview": (agent_output or "")[:500],
                },
            )

        norm_expected = _normalize(expected)
        norm_actual = _normalize(actual)
        passed = norm_expected == norm_actual
        return GradeResult(
            passed=passed,
            message="match" if passed else "mismatch",
            details={
                "expected": expected,
                "actual": actual,
                "normalized_expected": _stringify(norm_expected),
                "normalized_actual": _stringify(norm_actual),
            },
        )


def _stringify(obj: Any) -> Any:
    """Convert tuples to lists so the details dict round-trips through json.dumps."""
    if isinstance(obj, tuple):
        return [_stringify(x) for x in obj]
    if isinstance(obj, list):
        return [_stringify(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _stringify(v) for k, v in obj.items()}
    return obj
