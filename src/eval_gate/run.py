"""Score every case, decide release or block, write evidence and a report."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .policy import GatePolicy
from .scorers import score

REQUIRED_FIELDS = ("id", "input", "check", "note")


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: not valid JSON ({e.msg})") from None
    return rows


def load_cases(path: Path) -> list[dict]:
    cases, seen = load_jsonl(path), set()
    for c in cases:
        missing = [f for f in REQUIRED_FIELDS if not c.get(f)]
        if missing:
            raise ValueError(f"{path}: case {c.get('id', '?')} is missing {missing}")
        if c["id"] in seen:
            raise ValueError(f"{path}: case id {c['id']!r} appears twice")
        seen.add(c["id"])
    if not cases:
        raise ValueError(f"{path}: no cases. A gate with nothing to check passes everything.")
    return cases


def load_answers(path: Path) -> dict[str, str]:
    return {row["id"]: row["answer"] for row in load_jsonl(path)}


@dataclass(frozen=True)
class CaseResult:
    id: str
    passed: bool
    critical: bool
    why: str
    note: str


@dataclass(frozen=True)
class RunResult:
    policy: GatePolicy
    answers: Path
    results: list[CaseResult]

    @property
    def score(self) -> float:
        return round(sum(r.passed for r in self.results) / len(self.results), 4)

    @property
    def failed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed]

    @property
    def critical_failed(self) -> list[CaseResult]:
        return [r for r in self.failed if r.critical]

    @property
    def released(self) -> bool:
        return self.score >= self.policy.pass_mark and not self.critical_failed

    @property
    def verdict(self) -> str:
        if self.critical_failed:
            return "BLOCKED. A critical case failed."
        if not self.released:
            return "BLOCKED. Score is below the pass mark."
        return "RELEASE. Score meets the pass mark."


def evaluate(policy: GatePolicy, answers: Path | None = None) -> RunResult:
    answers = Path(answers or policy.answers)
    recorded = load_answers(answers)
    results = []
    for case in load_cases(policy.cases):
        passed, why = score(case, recorded.get(case["id"]))
        results.append(CaseResult(case["id"], passed, bool(case.get("critical")), why, case["note"]))
    return RunResult(policy, answers, results)


def record_live(cases: Path, answer_fn: Callable[[str], str], out: Path) -> Path:
    """Ask a real model each case and save the answers, so the run can be replayed."""
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"id": c["id"], "answer": answer_fn(c["input"])} for c in load_cases(cases)]
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return out


def commit_id() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True)
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def record_evidence(result: RunResult, clock: Callable[[], datetime] | None = None) -> dict:
    """Append one line per run. This file is the release evidence."""
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    p = result.policy
    record = {
        "ts": now.isoformat(), "commit": commit_id(), "answers": result.answers.as_posix(),
        "score": result.score, "pass_mark": p.pass_mark, "agreed_by": p.agreed_by,
        "agreed_on": p.agreed_on, "gate_sha256": p.sha256, "released": result.released,
        "cases_total": len(result.results), "cases_failed": [r.id for r in result.failed],
    }
    p.evidence.parent.mkdir(parents=True, exist_ok=True)
    with p.evidence.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return record


def report_markdown(result: RunResult) -> str:
    p = result.policy
    passed = len(result.results) - len(result.failed)
    lines = [
        "# Eval release gate", "",
        f"**{result.verdict}**", "",
        f"- Score: {result.score:.2f} ({passed}/{len(result.results)} cases)",
        f"- Pass mark: {p.pass_mark:.2f}, agreed by {p.agreed_by} on {p.agreed_on}",
        f"- Answers: `{result.answers.as_posix()}`",
        f"- Commit: `{commit_id()}`", "",
    ]
    if result.failed:
        lines += ["| Case | Critical | Why it failed | Failure it guards against |", "|---|---|---|---|"]
        for r in result.failed:
            lines.append(f"| {r.id} | {'yes' if r.critical else 'no'} | {r.why} | {r.note} |")
    else:
        lines.append("All cases passed.")
    return "\n".join(lines) + "\n"
