# Memskills — Recursive Language Model (RLM)

A Python toolkit that enables LLMs to process arbitrarily large inputs without loading full content into memory, solving the "context rot" problem where accuracy degrades as inputs approach context window limits.

## How It Works

Instead of stuffing entire files into prompts, RLM provides the LLM with only a **manifest** (file list with line counts) and lets the model drive its own exploration using structured tags:

| Tag | Purpose |
|-----|---------|
| `<peek file="..." lines="N-M"/>` | Read specific lines from a file |
| `<recurse query="..." file="..." lines="N-M"/>` | Delegate a sub-question to a fresh recursive call |
| `<answer>...</answer>` | Emit the final answer |

This mirrors how an expert developer reads unfamiliar code — skimming structure first, then drilling into relevant sections.

## Project Structure

```
memskills/
├── skills/rlm/
│   ├── rlm.py              # Main orchestrator (~240 lines, stdlib only)
│   ├── system_prompt.txt    # LLM system prompt for exploration
│   └── SKILL.md             # User-facing skill documentation
├── tests/
│   ├── niah/                # Needle-In-A-Haystack benchmark tools
│   ├── test_cli.py          # CLI integration tests
│   ├── test_manifest.py     # Manifest builder and filter tests
│   ├── test_prompt.py       # Prompt building tests
│   ├── test_rlm.py          # Core recursion logic tests
│   ├── test_tag_parser.py   # Tag parsing and validation tests
│   └── test_utils.py        # File I/O and LLM calling tests
├── docs/                    # Documentation and architecture records
├── requirements-dev.txt     # Dev dependencies (pytest)
└── .gitignore
```

## Prerequisites

- Python 3.9+
- A working `--llm-cmd` (any command that reads a prompt from stdin and writes a response to stdout)

## Quick Start

**Query a codebase:**
```bash
python skills/rlm/rlm.py \
  --query "Find all places that handle authentication" \
  --input ./src \
  --llm-cmd "claude -p"
```

**Query a long document:**
```bash
python skills/rlm/rlm.py \
  --query "Summarise the key findings" \
  --input report.txt \
  --llm-cmd "ollama run llama3"
```

**Read from stdin:**
```bash
cat notes.txt | python skills/rlm/rlm.py \
  --query "What action items are mentioned?" \
  --input - \
  --llm-cmd "claude -p"
```

**Filter files:**
```bash
python skills/rlm/rlm.py \
  --query "Find all SQL queries" \
  --input ./backend \
  --include "*.py" \
  --exclude "*/migrations/*" \
  --llm-cmd "claude -p"
```

## The `--llm-cmd` Contract

Any shell command that:
1. Reads the prompt from **stdin**
2. Writes the response to **stdout**

Examples:
```bash
--llm-cmd "claude -p"              # Claude Code
--llm-cmd "ollama run llama3"      # Ollama (local)
--llm-cmd "./my_agent.sh"          # Custom wrapper
```

Since `rlm.py` itself satisfies this contract, it can be used as an `--llm-cmd` inside another caller for chained recursive processing.

## CLI Reference

| Flag | Default | Description |
|------|---------|-------------|
| `--query` | *(required)* | Question to answer |
| `--input` | *(required)* | File, directory, or `-` for stdin |
| `--llm-cmd` | *(required)* | Shell command for the LLM backend |
| `--max-depth` | 4 | Maximum recursion depth |
| `--max-turns` | 10 | Maximum exploration turns per level |
| `--include` | `*` | Include only files matching glob (repeatable) |
| `--exclude` | none | Exclude files matching glob (repeatable) |

## Safety Limits

- **Max recursion depth** — prevents unbounded nesting
- **Max turns per level** — caps exploration at each recursion level
- **Global call budget** — `max_depth * max_turns * 2` total LLM calls across the entire run
- When limits are reached, the best partial answer accumulated so far is returned

## Pattern Matching

File filters use Python's `fnmatch`:
- `*.py` matches at any depth (`src/auth/login.py`) — `*` absorbs `/`
- `tests/*` only covers one level — `tests/sub/foo.py` is NOT excluded
- `**` glob syntax is NOT supported
- For depth-independent matching, omit slashes: `test_*.py` excludes test files anywhere

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Dependencies

**Runtime:** None — uses only Python standard library.
**Development:** `pytest`

## License

See project root for license information.
