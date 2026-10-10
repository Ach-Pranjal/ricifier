"""Explain one generated configuration line using the saved design context."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import ml_model as mm


PROMPT = """Explain one line from a generated Linux desktop configuration.
Use the supplied mood, theme, and aesthetic as context. Be concise but useful.
Mention what the setting controls, why this value fits the design, and any
behavioral effect the user should know. Do not suggest changing keybindings,
startup commands, scripts, includes, or other behavior.
Reply with ONLY a JSON object:
{"explanation":"two or three short paragraphs in one string"}

Application: <<APP>>
Line number: <<LINE_NUMBER>>
Configuration line: <<LINE>>
Design context: <<DESIGN>>"""


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: explain_parameter.py payload.json", file=sys.stderr)
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    prompt = (
        PROMPT.replace("<<APP>>", str(payload["app"]))
        .replace("<<LINE_NUMBER>>", str(payload["line_number"]))
        .replace("<<LINE>>", str(payload["line"]))
        .replace("<<DESIGN>>", json.dumps(payload["design"]))
    )
    response = mm._parse_json(mm._generate([prompt]))
    explanation = response.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        raise ValueError("Gemini did not return an explanation")
    print(json.dumps({"explanation": explanation.strip()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
