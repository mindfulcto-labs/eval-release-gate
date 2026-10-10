"""Example plugin: a DeepEval metric as a gate scorer.

Needs `uv sync --extra deepeval` and a judge model (DeepEval uses an LLM to
score, so set its API key). Load it with:
    uv run eval-gate check --plugin examples.deepeval_adapter
then use "check": "deepeval_relevancy" in a case. The case's "threshold"
field sets the per-case bar (default 0.7).
"""

from deepeval.metrics import AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase

from eval_gate import register


@register("deepeval_relevancy")
def deepeval_relevancy(case: dict, answer: str) -> tuple[bool, str]:
    metric = AnswerRelevancyMetric(threshold=case.get("threshold", 0.7))
    metric.measure(LLMTestCase(input=case["input"], actual_output=answer))
    ok = metric.is_successful()
    return ok, "" if ok else f"relevancy {metric.score:.2f} below {metric.threshold}"
