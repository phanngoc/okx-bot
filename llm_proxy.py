"""Claude CLI proxy — uses locally authenticated Claude Code as LLM API."""

import json
import re
import subprocess

DEFAULT_MODEL = "haiku"
MAX_BUDGET = 0.05


def ask_claude(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", model,
                "--output-format", "text",
                "--no-session-persistence",
                "--max-budget-usd", str(MAX_BUDGET),
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        print(f"  [LLM] Error: {e}")
        return ""


def ask_json(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 30) -> dict | None:
    raw = ask_claude(prompt, model, timeout)
    if not raw:
        return None
    match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
    if not match:
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if match:
            raw = match.group(1)
        else:
            return None
    else:
        raw = match.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
