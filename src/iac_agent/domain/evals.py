"""Domain models for the deterministic eval harness.

These describe the *outcome* of running an evaluator against a golden
scenario — they carry no evaluation logic themselves (that lives in
``evals.evaluators``) and no dataset-loading logic (that lives in
``evals.scenarios``). Phase 1 scoring is deliberately binary: 1.0 means
the expected behavior matched exactly, 0.0 means it did not. There is
no fuzzy/partial score.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvalStatus(StrEnum):
    """The outcome of running one evaluator against one scenario.

    PASS/FAIL describe product behavior (the system did or did not do
    what the scenario expected). ERROR is different in kind: the
    evaluator itself could not complete its check — a malformed
    scenario, an internal evaluation failure — and must never be
    silently treated as PASS or FAIL.
    """

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass(frozen=True)
class EvalResult:
    """The outcome of one evaluator run against one scenario."""

    scenario_id: str
    evaluator: str
    status: EvalStatus
    score: float
    message: str


@dataclass(frozen=True)
class EvalSuiteResult:
    """The aggregate outcome of running every evaluator over every scenario.

    ``results`` order is preserved exactly as produced by the runner
    (dataset order, then a fixed evaluator order per scenario) — it is
    not resorted here, since the runner is already the single source of
    deterministic ordering. All counts are derived properties, never
    stored, so they cannot drift from ``results``.
    """

    results: tuple[EvalResult, ...]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status is EvalStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status is EvalStatus.FAIL)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.status is EvalStatus.ERROR)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total * 100.0) if self.total else 0.0
