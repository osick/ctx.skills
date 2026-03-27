# RLM Skill Design — Recursive Language Model for Long Context

**Date:** 2026-03-27
**Status:** Approved
**Repo:** memskills

---

## Overview

A self-contained skill implementing Recursive Language Models (RLM) as described in
[Alex Zhang's blog post](https://alexzhang13.github.io/blog/2025/rlm/) and the
[arXiv paper (2512.24601)](https://arxiv.org/abs/2512.24601).

The skill enables any LLM to process arbitrarily large inputs (codebases, documents) by
never loading full content into the prompt. Instead, the LLM drives its own exploration
via structured tags, and the script resolves them incrementally.

**Primary use cases:**
- Long files and codebases (e.g. "find all authentication logic across this repo")
- Long external documents (e.g. research papers, logs, data files exceeding context limits)

---

## File Structure

```
skills/rlm/
  SKILL.md       — skill guide: concept, when to use, invocation examples
  rlm.py         — main orchestrator (entry point)
  prompt.py      — prompt templates, tag definitions, optional reference LLM adapter
```

Total: ~150-200 lines of Python. Zero mandatory dependencies beyond stdlib.

---

## Invocation

```bash
python rlm.py --query "Find all authentication logic" \
              --input ./src \
              --llm-cmd "claude -p"

python rlm.py --query "Summarize the methodology" \
              --input paper.txt \
              --llm-cmd "./my_adapter.sh"

cat document.txt | python rlm.py --query "What are the key findings?" \
                                  --input - \
                                  --llm-cmd "ollama run llama3"
```

---

## `--llm-cmd` Interface

The LLM backend is a shell command. Contract:

- **stdin** — the full prompt (string)
- **stdout** — the LLM's response (string)

Any script or binary satisfying this contract is valid: Claude Code agents, OpenAI wrappers,
Ollama, local models, mocks for testing. `rlm.py` itself satisfies the contract, making it
composable as a `--llm-cmd` for another caller.

`prompt.py` includes an optional ~20-line reference adapter using only stdlib + env vars
(`OPENAI_API_KEY`, `OPENAI_BASE_URL`) for OpenAI-compatible endpoints.

---

## Tag Vocabulary

The LLM communicates intent through exactly three tags:

| Tag | Purpose |
|-----|---------|
| `<peek file="path" lines="N-M"/>` | Request lines N–M of a file |
| `<recurse query="..." file="path" lines="N-M"/>` | Spawn recursive sub-call on a chunk |
| `<answer>...</answer>` | Emit final answer, terminate |

Tags are parsed from the LLM response after each turn. Unknown or missing tags trigger
graceful fallback: the full response is treated as the answer.

---

## Context Metadata (Manifest)

The LLM never receives file contents directly. It receives a manifest:

```
src/auth.py          lines 1-312
src/models/user.py   lines 1-89
src/utils/tokens.py  lines 1-54
```

For a single file: one entry. For stdin: written to a temp file, treated as one entry.
Actual content is only loaded on demand via `<peek>` or `<recurse>`.

---

## Recursion Protocol

```
load_input(--input)
  if directory → recursively walk all text files, build manifest {file: (start_line, end_line)}
  if file      → single manifest entry
  if stdin     → write to temp file, single manifest entry

send_to_llm(system_prompt + query + manifest)
  loop (up to --max-turns):
    parse tags from response
    <peek>    → load lines, append to context, re-send to LLM
    <recurse> → call rlm() recursively (fresh conversation, own turn loop)
                append only the sub-call's plain-text answer to context, re-send to LLM
    <answer>  → return answer text, exit loop
    no tag    → treat full response as answer (graceful fallback)
```

Each recursive call is a **fresh conversation** with its own independent turn loop.
Results bubble up as plain text strings.

---

## Safety Limits

| Flag | Default | Meaning |
|------|---------|---------|
| `--max-depth` | 4 | Maximum recursion depth |
| `--max-turns` | 10 | Maximum tag/response exchanges per recursion level |

Both are configurable at the CLI. When limits are reached, the best partial answer
accumulated so far is returned.

| Flag | Default | Meaning |
|------|---------|---------|
| `--include` | `*` | Glob pattern for files to include (e.g. `"*.py"`, `"src/**/*.ts"`) |
| `--exclude` | none | Glob pattern for files to exclude (e.g. `"**/test_*"`, `"*.min.js"`) |

Both flags apply only to directory traversal. Multiple patterns can be passed by repeating
the flag: `--exclude "*.min.js" --exclude "**/node_modules/**"`.

---

## SKILL.md Contents (outline)

1. **What is RLM** — 2-paragraph summary of the concept and why it beats context stuffing
2. **When to use** — large codebases, documents exceeding context, cross-file analysis
3. **Prerequisites** — Python 3.9+, a working `--llm-cmd`
4. **Quick start** — 3 copy-paste examples (codebase, document, stdin)
5. **Writing a `--llm-cmd` adapter** — the stdin/stdout contract, reference adapter pointer
6. **Composing skills** — using `rlm.py` as the `--llm-cmd` for another caller
7. **Limits and tuning** — `--max-depth`, `--max-turns`

---

## What is Out of Scope

- No REPL / code execution (Approach A was rejected for complexity)
- No built-in chunked map-reduce (Approach C was rejected — loses LLM-driven exploration)
- No SDK dependencies in `rlm.py` (adapters are optional, live in `prompt.py`)
- No PDF or binary file support — `--input` accepts plain text files and directories only
- No streaming output (stdout is written once, when `<answer>` is received)
- No persistent session state between runs

---

## Testing

- Unit tests for tag parser (valid tags, malformed tags, missing tags, mixed content)
- Unit tests for manifest builder (file, directory, stdin)
- Integration test using a mock `--llm-cmd` script that returns canned tag sequences
- Integration test verifying recursion depth limiting
- Integration test verifying graceful fallback on missing tags
