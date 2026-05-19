"""Grader interface.

`run_task.py` only depends on this protocol — the JSON-match grader for M1 and
a future DB-diff grader for write-style tasks (planned M2/M3) both slot in
without changing the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class GradeResult:
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class Grader(Protocol):
    def grade(self, task: dict, agent_output: str) -> GradeResult: ...
