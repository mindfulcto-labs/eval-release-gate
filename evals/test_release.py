"""The release gate as a single pytest test.

Fails the build below the pass mark, or when a critical case fails, and lists
each failed case with the failure it guards against. Point it at other
answers with EVAL_GATE_ANSWERS=path/to/answers.jsonl.
"""

import os
from pathlib import Path

from eval_gate import GatePolicy, evaluate

GATE = Path(__file__).parent / "gate.toml"


def test_release_gate():
    policy = GatePolicy.load(GATE)
    answers = os.environ.get("EVAL_GATE_ANSWERS")
    result = evaluate(policy, Path(answers) if answers else None)
    failed = "\n".join(f"  {r.id}: {r.why} (guards against: {r.note})" for r in result.failed)
    assert result.released, (
        f"{result.verdict} Score {result.score:.2f}, pass mark {policy.pass_mark:.2f}.\n{failed}"
    )
