# ontology — a Claude Code skill

Extract a typed node/edge ontology from a set of text documents, then search, edit, traverse, merge, and export it.

`SKILL.md` is the instruction file Claude reads when the skill is invoked. This README is for humans — what the skill does, how to install it, how to use it directly from the shell, and what its limits are.

---

## Install

Copy this directory to `~/.claude/skills/ontology/` (on Windows: `C:\Users\<you>\.claude\skills\ontology\`). Claude Code picks it up automatically on the next session.

### Python dependencies

- **`scripts/ontology.py`** — stdlib only. No install required. Works on Python 3.8+.
- **`scripts/ingest.py`** — only needed for binary input (PDF, DOCX, PPTX, HTML, …). Requires:
  ```bash
  pip install 'markitdown[all]'
  ```
  Plain text (`.txt`) and Markdown (`.md`) are handled without any dependency.

---

## Data model

Everything lives in one JSON file:

```json
{
  "meta": { "name": "...", "created": "...", "updated": "...", "sources": [...] },
  "nodes": [
    {"id": "Dog", "type": "Class", "label": "Dog", "props": {"aliases": ["dogs"]}}
  ],
  "edges": [
    {"source": "Dog", "target": "Mammal", "type": "subclass_of", "props": {}}
  ]
}
```

- **Node IDs are deterministic**: `id = slug(canonical_label)`. Two independent extractions of the same entity must produce the same ID. See `SKILL.md` for the exact rules (German umlaut transliteration, NFKD for other Latin diacritics, homonym disambiguation).
- **Edge types** follow a small controlled vocabulary: `subclass_of`, `instance_of`, `has_property`, `part_of`, `member_of`, `located_in`, `causes`, `precedes`, `related_to`, `synonym_of`, `defined_in`, `authored_by`, plus domain-specific types as needed.
- The file **is the source of truth**. Every CLI command reads and rewrites it. It diffs cleanly in git — use version control.

---

## Quick start

```bash
# create an empty ontology
python scripts/ontology.py -f ontology.json init --name my_onto

# add some knowledge
python scripts/ontology.py -f ontology.json add-node --label "Dog" --type Class
python scripts/ontology.py -f ontology.json add-node --label "Mammal" --type Class
python scripts/ontology.py -f ontology.json add-edge --source Dog --target Mammal --type subclass_of

# inspect
python scripts/ontology.py -f ontology.json stats
python scripts/ontology.py -f ontology.json validate
python scripts/ontology.py -f ontology.json search dog
python scripts/ontology.py -f ontology.json traverse Mammal --direction in --edge-type subclass_of

# export
python scripts/ontology.py -f ontology.json export svg     --out ontology.svg
python scripts/ontology.py -f ontology.json export mermaid --out ontology.mmd
python scripts/ontology.py -f ontology.json export graphml --out ontology.graphml
python scripts/ontology.py -f ontology.json export cypher  --out ontology.cypher
python scripts/ontology.py -f ontology.json export csv     --out ontology.csv
```

---

## Using the skill via Claude Code

Just ask in plain language. Triggers Claude will pick up:

- *"Extract an ontology from this PDF"*
- *"Build a knowledge graph from these docs"*
- *"Add `Dog subclass_of Mammal` to the ontology"*
- *"What subclasses of Mammal are in the ontology?"*
- *"Export the ontology for Neo4j"*

Claude reads `SKILL.md` and follows its workflow: ingest → extract → bulk-write JSON → validate → stats. For multi-document builds it applies the *Before each new document* checklist in `SKILL.md`.

---

## Exports

| Format | Consumes cleanly | Typical use |
|---|---|---|
| `svg` | Any browser, any image viewer | Static picture, zero external binaries (pure-Python layered layout) |
| `mermaid` | GitHub, VS Code, Obsidian, Notion, mermaid.live | Inline diagrams in docs/notes |
| `graphml` | Gephi, yEd, Cytoscape, Neo4j (APOC) | Interactive visualization, custom layouts |
| `cypher` | Neo4j (`:source` in cypher-shell) | Direct DB load via `MERGE` statements |
| `csv` | Neo4j `LOAD CSV`, pandas, ArangoDB | Bulk DB import, data-science workflows |

Exports are lossless: the JSON stays the source of truth, and adding a new export target means adding one function to `scripts/ontology.py`.

---

## Operations reference

All commands take `-f <path>` (defaults to `ontology.json`).

| Command | Purpose |
|---|---|
| `init [--name NAME]` | Create an empty ontology file. |
| `add-node --label L [--id ID] [--type T] [--props JSON] [--update]` | Add or update a node. Omitting `--id` applies `slug(--label)`. |
| `add-edge --source S --target T --type R [--props JSON]` | Add a directed edge. |
| `remove-node ID` | Remove a node and every edge that touches it. |
| `remove-edge [--source S] [--target T] [--type R]` | Remove all edges matching the filters (at least one required). |
| `search [QUERY] [--type T] [--edge-type R] [--source S] [--target T] [--json]` | Substring search on nodes and edges. |
| `traverse NODE [--direction in\|out\|both] [--edge-type R] [--depth N] [--json]` | BFS from a node. |
| `merge OTHER [--overwrite]` | Merge `OTHER` into `-f` file. Dedupes on node ID and exact edge triple. |
| `stats` | Node/edge counts, broken down by type. |
| `validate` | Duplicate-ID and dangling-edge checks. |
| `export FORMAT [--out PATH]` | Export to `graphml`, `cypher`, `csv`, `svg`, or `mermaid`. |

---

## Growing an ontology across many documents

Use the **Before each new document** checklist in `SKILL.md`. The short version:

1. `stats` the master → see what's there, especially which edge types.
2. `search` for entities likely to overlap, **before** proposing new nodes.
3. Canonicalize the label. Compute the ID with `slug(label)` — deterministically.
4. Bulk-write `ontology_<docname>.json`. Don't call `add-node` in a loop.
5. `validate` the per-doc file.
6. `merge` into the master. Read the conflict report.
7. `search` for same-label-different-ID pairs — dedup failures.
8. Commit.

---

## Practical limits

Rough bounds based on where things actually break first:

| Limit | Size | What breaks |
|---|---|---|
| One document per extraction | ~30 pages / ~20k tokens | LLM attention degrades; duplicates rise. Chunk larger docs. |
| Claude reads full `ontology.json` | ~5–20k nodes | Context window fills. Past this, use the CLI for all interaction. |
| CLI `search` / `traverse` | ~100k–1M nodes | Linear scans stay fast until the upper end. |
| Bulk `add-node` in a loop | ~2k calls | Each call rewrites the whole file. Bulk-write JSON instead. |
| Dedup quality | ~2–10k entities | The real ceiling. Canonical labels + deterministic IDs keep this healthy longer. |

Past ~10k entities the JSON-file model starts to creak, and you should consider moving to a real graph DB (Neo4j + APOC). Until then, this skill is the right primitive.

---

## File layout

```
ontology/
├── README.md            # this file — for humans
├── SKILL.md             # instructions Claude reads
└── scripts/
    ├── ontology.py      # stdlib-only CLI: CRUD, search, traverse, merge, export
    └── ingest.py        # markitdown wrapper for PDF/DOCX/PPTX/HTML → text
```
