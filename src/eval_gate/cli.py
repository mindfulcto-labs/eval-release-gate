"""Command line: run the gate, exit non-zero to block the release, show past runs."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

from .policy import GatePolicy, PolicyError
from .run import evaluate, load_jsonl, record_evidence, record_live, report_markdown


def _import(spec: str):
    sys.path.insert(0, os.getcwd())
    module, _, attr = spec.partition(":")
    mod = importlib.import_module(module)
    return getattr(mod, attr) if attr else mod


def cmd_check(args: argparse.Namespace) -> int:
    for plugin in args.plugin:
        _import(plugin)  # a plugin registers extra scorers when imported
    try:
        policy = GatePolicy.load(args.gate)
    except (PolicyError, FileNotFoundError) as e:
        print(f"gate refused to run: {e}", file=sys.stderr)
        return 2
    answers = Path(args.answers) if args.answers else None
    if args.live:
        answers = record_live(policy.cases, _import(args.live), Path(args.report).parent / "live-answers.jsonl")
    try:
        result = evaluate(policy, answers)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"gate refused to run: {e}", file=sys.stderr)
        return 2

    print(f"pass mark  {policy.pass_mark:.2f}  agreed by {policy.agreed_by} on {policy.agreed_on}")
    print(f"answers    {result.answers.as_posix()}\n")
    width = max(len(r.id) for r in result.results)
    for r in result.results:
        flag = " [critical]" if r.critical else ""
        detail = "" if r.passed else f"  {r.why}{flag}"
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.id:<{width}}{detail}".rstrip())
        if not r.passed:
            print(f"        guards against: {r.note}")
    passed = len(result.results) - len(result.failed)
    print(f"\nscore {result.score:.2f} ({passed}/{len(result.results)}), pass mark {policy.pass_mark:.2f}")
    print(f"RESULT: {result.verdict}")

    record_evidence(result)
    report = report_markdown(result)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as f:
            f.write(report)
    print(f"report     {args.report}\nevidence   {policy.evidence.as_posix()}")
    return 0 if result.released else 1


def cmd_history(args: argparse.Namespace) -> int:
    path = Path(args.evidence)
    if not path.exists():
        print(f"no evidence yet at {path}")
        return 0
    print(f"{'when (UTC)':<20} {'commit':<13} {'score':>5} {'mark':>5}  result   failed")
    for r in load_jsonl(path):
        result = "release" if r["released"] else "BLOCKED"
        failed = ", ".join(r["cases_failed"]) or "-"
        print(f"{r['ts'][:19]:<20} {r['commit']:<13} {r['score']:>5.2f} {r['pass_mark']:>5.2f}  {result:<8} {failed}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval-gate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="score the answers and block the release below the pass mark")
    c.add_argument("--gate", default="evals/gate.toml")
    c.add_argument("--answers", help="recorded answers (JSONL); defaults to the one named in the gate file")
    c.add_argument("--live", metavar="MODULE:FUNC", help="call a real model through this function instead")
    c.add_argument("--plugin", action="append", default=[], metavar="MODULE", help="import extra scorers")
    c.add_argument("--report", default="runs/report.md")
    c.set_defaults(func=cmd_check)
    h = sub.add_parser("history", help="list past gate runs from the evidence file")
    h.add_argument("--evidence", default="runs/evidence.jsonl")
    h.set_defaults(func=cmd_history)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
