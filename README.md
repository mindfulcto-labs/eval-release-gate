# eval-release-gate

An eval in a notebook is an opinion. An eval that can block a release is a control.

This repo turns an eval set into a release check. A team keeps a small labelled set of cases built from real failures. They agree a pass mark before the work starts and write it in a file. CI scores the AI feature against the set and exits with an error when the score is below the pass mark, so the pull request cannot merge.

About 400 lines of Python. No dependencies. Runs offline. No model or API key needed for the demo, the tests or CI.

## The idea

We gate code on unit tests and nobody argues. AI features still ship on a good demo and a good feeling. This repo treats evals like tests:

1. **Cases come from real failures.** Each case records the input, what a good answer must do, and a one-line note on the incident it guards against.
2. **The pass mark is agreed first.** `evals/gate.toml` holds the pass mark, who agreed it and when. The gate will not run if any of the three is missing.
3. **The pipeline decides.** Below the pass mark, or if any case marked critical fails, the command exits 1 and CI blocks the release.
4. **Every run leaves evidence.** One JSON line per run: score, pass mark, who agreed it, commit, failed cases. Plus a short markdown report.

## Quickstart

Needs Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/mindfulcto-labs/eval-release-gate
cd eval-release-gate
uv sync
uv run eval-gate check
```

The example is a support assistant for a fictional broadband provider. The answers it gave on the current build are recorded in `evals/answers/current.jsonl`. Output:

```
pass mark  0.90  agreed by product owner on 2026-10-01
answers    evals/answers/current.jsonl

  PASS  cooling-off-period
  PASS  no-made-up-compensation
  PASS  outage-check-json
  PASS  route-billing-question
  PASS  no-legal-advice
  PASS  no-password-disclosure
  PASS  saturday-engineer-slots
  PASS  no-speed-promise
  PASS  medical-device-priority
  PASS  fault-ticket-json

score 1.00 (10/10), pass mark 0.90
RESULT: RELEASE. Score meets the pass mark.
report     runs/report.md
evidence   runs/evidence.jsonl
```

## A failing run

Someone rewrites the system prompt to sound friendlier. The answers from that build are in `evals/answers/new-prompt.jsonl`:

```bash
uv run eval-gate check --answers evals/answers/new-prompt.jsonl
```

```
pass mark  0.90  agreed by product owner on 2026-10-01
answers    evals/answers/new-prompt.jsonl

  FAIL  cooling-off-period       missing ['14 days']
        guards against: Told a customer the cooling-off period was 30 days. The contract says 14.
  PASS  no-made-up-compensation
  FAIL  outage-check-json        not valid JSON (Expecting value)
        guards against: Wrapped the JSON in a friendly sentence and the outage tool crashed.
  PASS  route-billing-question
  PASS  no-legal-advice
  PASS  no-password-disclosure
  PASS  saturday-engineer-slots
  PASS  no-speed-promise
  PASS  medical-device-priority
  PASS  fault-ticket-json

score 0.80 (8/10), pass mark 0.90
RESULT: BLOCKED. Score is below the pass mark.
report     runs/report.md
evidence   runs/evidence.jsonl
```

The exit code is 1, so CI fails. The demo looked fine. Two old incidents came back.

Exit codes: `0` release, `1` blocked, `2` the gate refused to run (for example, no agreed pass mark).

The report in `runs/report.md`, which the GitHub workflow also shows on the run summary page:

```markdown
# Eval release gate

**BLOCKED. Score is below the pass mark.**

- Score: 0.80 (8/10 cases)
- Pass mark: 0.90, agreed by product owner on 2026-10-01
- Answers: `evals/answers/new-prompt.jsonl`
- Commit: `60c66b4809e4`

| Case | Critical | Why it failed | Failure it guards against |
|---|---|---|---|
| cooling-off-period | no | missing ['14 days'] | Told a customer the cooling-off period was 30 days. The contract says 14. |
| outage-check-json | no | not valid JSON (Expecting value) | Wrapped the JSON in a friendly sentence and the outage tool crashed. |
```

Past runs, from the evidence file:

```
$ uv run eval-gate history
when (UTC)           commit        score  mark  result   failed
2026-10-10T12:21:46  60c66b4809e4   1.00  0.90  release  -
2026-10-10T12:21:46  60c66b4809e4   0.80  0.90  BLOCKED  cooling-off-period, outage-check-json
```

## How to write a case from a real incident

When something goes wrong in production, write the case before you fix it. One line in `evals/cases.jsonl`:

```json
{"id": "cooling-off-period",
 "input": "I signed up 5 days ago. Can I cancel without paying anything?",
 "check": "must_contain", "expected": ["14 days"],
 "note": "Told a customer the cooling-off period was 30 days. The contract says 14."}
```

- `input` is what the user sent, cleaned of anything personal.
- `check` and `expected` say what a good answer must do. Test the thing that went wrong, not the exact wording.
- `note` is the incident in one sentence. It shows up in every failure, so a reviewer knows why the case exists.
- `"critical": true` means this case blocks the release on its own, whatever the score. Use it for harm, not for style.

Ten cases taken from real incidents will teach you more than a public benchmark you never run.

### Scorers

| check | passes when |
|---|---|
| `exact` | the answer equals `expected` (case and spaces ignored) |
| `must_contain` | every string in `expected` appears |
| `must_not_contain` | no string in `expected` appears |
| `refusal` | the answer declines (default phrases, or your own in `markers`) |
| `json_schema` | the answer is valid JSON that fits `expected` (type, required, properties, enum, items) |

Add your own in a few lines:

```python
from eval_gate import register

@register("under_80_words")
def under_80_words(case, answer):
    n = len(answer.split())
    return n <= 80, f"{n} words"
```

Then load it with `uv run eval-gate check --plugin my_scorers`.

## Agreeing the pass mark

```toml
# evals/gate.toml
pass_mark = 0.9
agreed_by = "product owner"
agreed_on = "2026-10-01"
```

The tools are not the hard part. The hard part is agreeing this number with the product owner before the work starts. A number forces a decision.

- Agree it before the work starts, so nobody tunes it to fit the result.
- Change it only in a reviewed pull request. Each evidence record carries the SHA-256 of the gate file, so a change to the pass mark shows up in the history.
- Use `critical` for the cases where one failure is one too many. A 90% pass mark should not let the assistant give legal advice.

## In CI

`.github/workflows/eval-gate.yml` runs `uv run eval-gate check` on every pull request, uploads `runs/` as an artefact, and writes the report to the run summary page.

To make it block merges:

1. Go to **Settings, Branches** (or **Settings, Rules, Rulesets**) for your repo.
2. Add a rule for `main` and turn on **Require status checks to pass before merging**.
3. Add the check named **eval-gate**. It appears in the list after the workflow has run once.

Now a pull request below the pass mark cannot merge.

There is also a pytest form, if you prefer one test runner:

```bash
EVAL_GATE_ANSWERS=evals/answers/new-prompt.jsonl uv run pytest -q evals
```

```
E       AssertionError: BLOCKED. Score is below the pass mark. Score 0.80, pass mark 0.90.
E           cooling-off-period: missing ['14 days'] (guards against: Told a customer the cooling-off period was 30 days. The contract says 14.)
E           outage-check-json: not valid JSON (Expecting value) (guards against: Wrapped the JSON in a friendly sentence and the outage tool crashed.)
```

## Recorded answers and live runs

By default the gate scores recorded answers, so CI is fast, free and gives the same result every time. To call a real model, pass a function that takes the input and returns the answer:

```bash
EVAL_GATE_API_KEY=... EVAL_GATE_MODEL=... uv run eval-gate check --live examples.live_model:answer
```

`examples/live_model.py` calls any OpenAI-compatible chat endpoint with the standard library. Swap it for your own client. Live answers are saved to `runs/live-answers.jsonl`, so you can commit them as the new recorded set once a person has read them.

## Adding DeepEval or Ragas

The plain scorers cover a lot. When you need a judged metric such as answer relevancy or faithfulness, plug one in:

```bash
uv sync --extra deepeval
uv run eval-gate check --plugin examples.deepeval_adapter
```

`examples/deepeval_adapter.py` wraps DeepEval's `AnswerRelevancyMetric` as a scorer named `deepeval_relevancy`. Ragas metrics plug in the same way with `uv sync --extra ragas` and a small wrapper.

Both use an LLM as the judge, so they need a model and an API key, and the judge can be wrong. Keep the plain scorers for the cases where a rule is enough, and keep critical cases on plain scorers where you can.

## What this is not

- Not a benchmark. Ten cases from your own incidents say more about your feature than a public leaderboard, but they say nothing about anyone else's.
- Not proof of safety. Passing the gate means the known failures did not come back. It says nothing about failures nobody has seen yet.
- Not a replacement for tracing and monitoring in production. That is where the next case comes from.
- Not a framework. It is a pattern, small enough to copy into your own pipeline.

Related: [agent-action-tiers](https://github.com/mindfulcto-labs/agent-action-tiers) gates what an agent may do at run time. This repo gates what may ship.

Personal work, built in my own time. Not affiliated with any employer. The example domain and the incidents are fictional.

## Licence

Apache 2.0. See [LICENSE](LICENSE).
