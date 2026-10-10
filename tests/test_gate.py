import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from eval_gate import GatePolicy, PolicyError, evaluate, record_evidence, register, report_markdown, score
from eval_gate.cli import main

EVALS = Path(__file__).parent.parent / "evals"
FIXED = datetime(2026, 1, 1, tzinfo=timezone.utc)


def gate_file(tmp_path, body=None, answers=None):
    """A gate file in tmp_path that points at the real cases."""
    body = body if body is not None else 'pass_mark = 0.9\nagreed_by = "product owner"\nagreed_on = "2026-10-01"\n'
    answers = answers or (EVALS / "answers" / "current.jsonl")
    path = tmp_path / "gate.toml"
    path.write_text(body + f'cases = "{(EVALS / "cases.jsonl").as_posix()}"\n'
                    f'answers = "{Path(answers).as_posix()}"\nevidence = "{(tmp_path / "ev.jsonl").as_posix()}"\n')
    return path


def write_answers(tmp_path, changes):
    rows = [json.loads(line) for line in (EVALS / "answers" / "current.jsonl").read_text().splitlines()]
    for r in rows:
        r["answer"] = changes.get(r["id"], r["answer"])
    path = tmp_path / "answers.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


@pytest.mark.parametrize("check, expected, answer, ok", [
    ("exact", "billing", "  Billing ", True),
    ("exact", "billing", "billing question", False),
    ("must_contain", ["14 days"], "within 14 DAYS", True),
    ("must_contain", ["8am", "1pm"], "from 8am", False),
    ("must_not_contain", ["£100"], "you get £100", False),
    ("must_not_contain", ["£100"], "I have logged it", True),
    ("refusal", None, "I can’t share that.", True),
    ("refusal", None, "Your password is hunter2", False),
])
def test_plain_scorers(check, expected, answer, ok):
    assert score({"id": "t", "check": check, "expected": expected}, answer)[0] is ok


@pytest.mark.parametrize("answer, why", [
    ('{"postcode": "LS1", "status": "outage"}', ""),
    ('Sure! {"postcode": "LS1"}', "not valid JSON"),
    ('{"postcode": "LS1"}', "$.status is missing"),
    ('{"postcode": "LS1", "status": "down"}', "$.status is 'down'"),
    ('{"postcode": 7, "status": "outage"}', "$.postcode should be string"),
])
def test_json_schema(answer, why):
    schema = {"type": "object", "required": ["postcode", "status"], "properties": {
        "postcode": {"type": "string"}, "status": {"type": "string", "enum": ["outage", "no_outage"]}}}
    ok, got = score({"id": "t", "check": "json_schema", "expected": schema}, answer)
    assert ok is (why == "") and got.startswith(why)


def test_missing_answer_fails_and_unknown_check_raises():
    assert score({"id": "t", "check": "exact", "expected": "x"}, None) == (False, "no recorded answer for this case")
    with pytest.raises(ValueError, match="unknown check"):
        score({"id": "t", "check": "vibes"}, "fine")


def test_custom_scorer_can_be_registered():
    register("short")(lambda case, answer: (len(answer) < 20, "too long"))
    assert score({"id": "t", "check": "short"}, "ok")[0]


@pytest.mark.parametrize("missing", ["pass_mark", "agreed_by", "agreed_on"])
def test_gate_refuses_without_agreement(tmp_path, missing):
    lines = {"pass_mark": "pass_mark = 0.9", "agreed_by": 'agreed_by = "po"', "agreed_on": 'agreed_on = "2026-10-01"'}
    body = "".join(v + "\n" for k, v in lines.items() if k != missing)
    with pytest.raises(PolicyError, match=missing):
        GatePolicy.load(gate_file(tmp_path, body))


@pytest.mark.parametrize("bad", ["pass_mark = 0\n", "pass_mark = 1.5\n"])
def test_gate_rejects_silly_pass_marks(tmp_path, bad):
    with pytest.raises(PolicyError):
        GatePolicy.load(gate_file(tmp_path, bad + 'agreed_by = "po"\nagreed_on = "2026-10-01"\n'))


def test_current_answers_release(tmp_path):
    result = evaluate(GatePolicy.load(gate_file(tmp_path)))
    assert result.released and result.score == 1.0 and not result.failed


def test_new_prompt_is_blocked_below_pass_mark(tmp_path):
    result = evaluate(GatePolicy.load(gate_file(tmp_path)), EVALS / "answers" / "new-prompt.jsonl")
    assert not result.released and result.score == 0.8
    assert [r.id for r in result.failed] == ["cooling-off-period", "outage-check-json"]


def test_exactly_at_pass_mark_releases(tmp_path):
    answers = write_answers(tmp_path, {"cooling-off-period": "You have 30 days."})
    result = evaluate(GatePolicy.load(gate_file(tmp_path)), answers)
    assert result.score == 0.9 and result.released


def test_critical_failure_blocks_even_above_pass_mark(tmp_path):
    answers = write_answers(tmp_path, {"no-made-up-compensation": "You will get £100 today."})
    result = evaluate(GatePolicy.load(gate_file(tmp_path)), answers)
    assert result.score == 0.9 and not result.released
    assert "critical" in result.verdict


def test_evidence_is_appended_per_run(tmp_path):
    policy = GatePolicy.load(gate_file(tmp_path))
    record_evidence(evaluate(policy), clock=lambda: FIXED)
    record_evidence(evaluate(policy, EVALS / "answers" / "new-prompt.jsonl"), clock=lambda: FIXED)
    rows = [json.loads(line) for line in policy.evidence.read_text().splitlines()]
    assert [r["released"] for r in rows] == [True, False]
    assert rows[1]["cases_failed"] == ["cooling-off-period", "outage-check-json"]
    assert rows[0]["agreed_by"] == "product owner" and rows[0]["gate_sha256"] == policy.sha256


def test_report_lists_failures_with_the_incident(tmp_path):
    result = evaluate(GatePolicy.load(gate_file(tmp_path)), EVALS / "answers" / "new-prompt.jsonl")
    md = report_markdown(result)
    assert "BLOCKED" in md and "cooling-off period was 30 days" in md


def test_cli_exit_codes(tmp_path, capsys):
    gate, report = str(gate_file(tmp_path)), str(tmp_path / "report.md")
    assert main(["check", "--gate", gate, "--report", report]) == 0
    assert main(["check", "--gate", gate, "--report", report,
                 "--answers", str(EVALS / "answers" / "new-prompt.jsonl")]) == 1
    (tmp_path / "bad.toml").write_text("pass_mark = 0.9\n")
    assert main(["check", "--gate", str(tmp_path / "bad.toml"), "--report", report]) == 2
    assert "BLOCKED" in Path(report).read_text()
    assert main(["history", "--evidence", str(tmp_path / "ev.jsonl")]) == 0
    assert "BLOCKED" in capsys.readouterr().out


def test_live_mode_records_then_scores(tmp_path):
    mod = tmp_path / "fake_model.py"
    mod.write_text("def answer(prompt):\n    return 'billing'\n")
    import sys
    sys.path.insert(0, str(tmp_path))
    try:
        code = main(["check", "--gate", str(gate_file(tmp_path)), "--live", "fake_model:answer",
                     "--report", str(tmp_path / "out" / "report.md")])
    finally:
        sys.path.remove(str(tmp_path))
    assert code == 1 and (tmp_path / "out" / "live-answers.jsonl").exists()
