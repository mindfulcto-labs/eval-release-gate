"""A labelled eval set, a pass mark agreed in advance, and a CI check that blocks the release below it."""

from .policy import GatePolicy, PolicyError
from .run import CaseResult, RunResult, evaluate, record_evidence, report_markdown
from .scorers import SCORERS, register, score

__all__ = [
    "CaseResult", "GatePolicy", "PolicyError", "RunResult", "SCORERS",
    "evaluate", "record_evidence", "register", "report_markdown", "score",
]
__version__ = "0.1.0"
