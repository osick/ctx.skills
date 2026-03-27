"""Prompt templates for RLM and optional reference LLM adapter.

When run as a script (`python prompt.py`), acts as an OpenAI-compatible adapter:
  reads prompt from stdin, calls chat completions, writes response to stdout.

Required env: OPENAI_API_KEY
Optional env: OPENAI_BASE_URL  (default: https://api.openai.com/v1)
              OPENAI_MODEL     (default: gpt-4o-mini)
"""

SYSTEM_PROMPT = """\
You are an expert analyst equipped with tools to explore large inputs without loading them fully into memory.

You will receive:
1. A query to answer
2. A manifest listing available files and their line ranges, one file per line:
      path/to/file.py    lines N-M
3. Any context gathered from previous tool uses

Respond using EXACTLY ONE of these tags per message:

  <peek file="path/to/file" lines="N-M"/>
      Request lines N through M of a file. Inspect content before drawing conclusions.

  <recurse query="your sub-question" file="path/to/file" lines="N-M"/>
      Delegate analysis of a section to a fresh sub-call. Its answer will be returned to you.

  <answer>your complete answer here</answer>
      Emit your final answer when you have enough information.

Rules:
- Never guess. Always peek at content before making claims about it.
- Use recurse for sections too large to peek at once.
- Emit exactly one tag per response. Any text outside the tag is ignored by the parser.
"""


def build_prompt(query: str, manifest: dict, context_items: list = None) -> str:
    manifest_text = "\n".join(
        f"{path}    lines {start}-{end}"
        for path, (start, end) in manifest.items()
    )
    prompt = f"{SYSTEM_PROMPT}\n## Manifest\n\n{manifest_text}\n\n## Query\n\n{query}"
    if context_items:
        prompt += "\n\n## Context gathered so far\n\n" + "\n\n---\n\n".join(context_items)
    return prompt
