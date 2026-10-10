"""The gate file: the pass mark, who agreed it, and when."""

from __future__ import annotations

import hashlib
import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class PolicyError(ValueError):
    """The gate file is missing something, so the gate will not run."""


@dataclass(frozen=True)
class GatePolicy:
    pass_mark: float
    agreed_by: str
    agreed_on: str
    cases: Path
    answers: Path
    evidence: Path
    sha256: str  # hash of the gate file, so a changed pass mark shows up in the evidence

    @classmethod
    def load(cls, path: str | Path) -> "GatePolicy":
        path = Path(path)
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode())
        for key in ("pass_mark", "agreed_by", "agreed_on"):
            if data.get(key) in (None, ""):
                raise PolicyError(
                    f"{path}: '{key}' is missing. Agree the pass mark, who agreed it "
                    "and when, before the gate can run."
                )
        pass_mark = float(data["pass_mark"])
        if not 0 < pass_mark <= 1:
            raise PolicyError(f"{path}: pass_mark must be above 0 and at most 1, got {pass_mark}")
        try:
            agreed_on = date.fromisoformat(str(data["agreed_on"])).isoformat()
        except ValueError:
            raise PolicyError(f"{path}: agreed_on must be a date like 2026-10-01") from None
        base = path.parent
        return cls(
            pass_mark=pass_mark,
            agreed_by=str(data["agreed_by"]),
            agreed_on=agreed_on,
            cases=Path(os.path.normpath(base / data.get("cases", "cases.jsonl"))),
            answers=Path(os.path.normpath(base / data.get("answers", "answers/current.jsonl"))),
            evidence=Path(os.path.normpath(base / data.get("evidence", "../runs/evidence.jsonl"))),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
