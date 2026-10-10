"""Example --live hook: any OpenAI-compatible chat endpoint, standard library only.

Set EVAL_GATE_API_KEY, EVAL_GATE_MODEL and, if needed, EVAL_GATE_BASE_URL, then run:
    uv run eval-gate check --live examples.live_model:answer
Swap this file for your own client. The gate only needs a function str -> str.
"""

import json
import os
import urllib.request

SYSTEM = "You are the support assistant for a fictional broadband provider. Be brief."


def answer(prompt: str) -> str:
    key = os.environ.get("EVAL_GATE_API_KEY")
    if not key:
        raise SystemExit("EVAL_GATE_API_KEY is not set. Use recorded answers, or set a key for --live.")
    base = os.environ.get("EVAL_GATE_BASE_URL", "https://api.openai.com/v1")
    body = {"model": os.environ["EVAL_GATE_MODEL"], "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["choices"][0]["message"]["content"]
