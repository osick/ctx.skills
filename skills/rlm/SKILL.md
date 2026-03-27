---
name: rlm
description: Use when a query requires analysing files or documents that are too large to
  fit in a single LLM context window. Runs rlm.py to let any LLM explore the content
  recursively via peek/recurse/answer tags without loading it all into the prompt.
---

# Recursive Language Model (RLM)

## What is RLM

Standard LLMs degrade on long inputs — accuracy drops as the context window fills up
("context rot"). RLM avoids this by never loading full content into the prompt. Instead,
the model receives only a **manifest** (a list of files and line counts) and navigates the
content on demand using structured tags.

The model drives its own exploration: it peeks at specific lines, delegates sub-questions
to recursive sub-calls, and emits an answer when it has enough information. This mirrors
how an expert developer reads an unfamiliar codebase — skimming structure, drilling into
relevant sections, ignoring noise.

## When to use

- Analysing a large codebase for a cross-cutting concern ("find all places that touch auth")
- Summarising or querying a long document (research paper, log file, data export)
- Any question where the relevant content is spread across many files or sections
- When a direct prompt exceeds the model's context limit

**Not needed for:** small files that fit comfortably in a single prompt.

## Prerequisites

- Python 3.9+
- A working `--llm-cmd` (see below)

## Quick start

**Query a codebase:**
```bash
python skills/rlm/rlm.py \
  --query "Find all places that handle authentication" \
  --input ./src \
  --llm-cmd "claude -p"
```

**Query a document:**
```bash
python skills/rlm/rlm.py \
  --query "Summarise the key findings" \
  --input report.txt \
  --llm-cmd "python skills/rlm/prompt.py"
```

**Query from stdin:**
```bash
cat notes.txt | python skills/rlm/rlm.py \
  --query "What action items are mentioned?" \
  --input - \
  --llm-cmd "ollama run llama3"
```

**Filter files in a large repo:**
```bash
python skills/rlm/rlm.py \
  --query "Find all SQL queries" \
  --input ./backend \
  --include "*.py" \
  --exclude "*/migrations/*" \
  --llm-cmd "claude -p"
```

## The `--llm-cmd` contract

`--llm-cmd` is any shell command that:
- reads the prompt from **stdin**
- writes the response to **stdout**

Examples:
```bash
# Claude Code
--llm-cmd "claude -p"

# Reference OpenAI adapter (included in this skill)
export OPENAI_API_KEY=sk-...
--llm-cmd "python skills/rlm/prompt.py"

# Ollama (local model)
--llm-cmd "ollama run llama3"

# Custom wrapper script
--llm-cmd "./my_agent.sh"
```

`rlm.py` itself satisfies the contract — you can use it as a `--llm-cmd` inside another
caller to chain recursive processing.

## Tuning

| Flag | Default | When to change |
|------|---------|---------------|
| `--max-depth` | 4 | Increase for deeply nested recursion; lower to cut cost |
| `--max-turns` | 10 | Increase if model needs more exploration turns per level |
| `--include` | `*` | Restrict to relevant file types (`--include "*.py"`) |
| `--exclude` | none | Skip noise (`--exclude "*.min.js"`) |

When limits are reached, the best partial answer accumulated so far is returned.

## Pattern matching notes

File filters use Python's `fnmatch`. Key behaviour:
- `*.py` matches at any depth (e.g. `src/auth/login.py`) — `*` absorbs `/`
- `tests/*` only covers **one** level deep — `tests/sub/foo.py` is NOT excluded
- `**` glob syntax is NOT supported
- For depth-independent matching, omit slashes: `test_*.py` excludes test files anywhere
