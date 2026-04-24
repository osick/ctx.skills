---
name: ontology
description: Extract an ontology (typed nodes + typed edges) from a set of text documents, then search, traverse, edit, merge, and export it. Input formats: .txt, .md, and any binary (PDF/DOCX/PPTX/HTML) via markitdown. Canonical storage: a single ontology.json file. Export targets: GraphML (Gephi/yEd/Cytoscape), Cypher (Neo4j), CSV (nodes/edges for LOAD CSV), SVG (pure-Python image, no binary dependency), Mermaid (inline-renderable diagram text for GitHub / VS Code / Obsidian / mermaid.live).
---

# Ontology skill

Build and operate on an ontology extracted from unstructured text.

## When to use

- User provides one or more text documents and asks to **extract an ontology / knowledge graph / concept map / entity-relation model** from them.
- User has an existing `ontology.json` and wants to **search, traverse, edit, merge, or export** it.
- User wants to **feed the result into a graph DB** (Neo4j, ArangoDB, Kùzu, Memgraph) or a visualization tool (Gephi, yEd, Cytoscape, Graphviz).

Do **not** use this skill for free-form summarization, simple keyword extraction, or when the user just wants a list of topics.

## Storage format — `ontology.json`

Single JSON file. This is the source of truth. Every operation reads/writes this file.

```json
{
  "meta": {
    "name": "my_ontology",
    "created": "2026-04-24T10:00:00+00:00",
    "updated": "2026-04-24T10:00:00+00:00",
    "sources": ["paper1.pdf", "notes.md"]
  },
  "nodes": [
    {"id": "Dog",    "type": "Class",    "label": "Dog",   "props": {"source": "paper1.pdf"}},
    {"id": "Mammal", "type": "Class",    "label": "Mammal"},
    {"id": "Rex",    "type": "Instance", "label": "Rex"}
  ],
  "edges": [
    {"source": "Dog", "target": "Mammal", "type": "subclass_of"},
    {"source": "Rex", "target": "Dog",    "type": "instance_of"},
    {"source": "Rex", "target": "Alice",  "type": "owned_by", "props": {"since": "2020"}}
  ]
}
```

### Rules

- **`id`** is stable, unique, and slug-like (letters, digits, underscore). Prefer a slugified label. Treat it as a primary key.
- **`label`** is the human-readable name. Can change without breaking edges.
- **`type`** on nodes is a short controlled vocabulary (see below). On edges it is a snake_case relation name.
- **`props`** is an optional dict for anything else (source document, page, confidence, date, aliases, etc.).
- Edges are **directed**. An undirected relation like `synonym_of` should still be written once; consumers can treat the type as symmetric.

### Recommended controlled vocabularies

Node types (extend as needed, but stay consistent inside one ontology):
`Class`, `Instance`, `Property`, `Event`, `Process`, `Person`, `Organization`, `Location`, `Artifact`, `Concept`, `Document`.

Edge types (extend as needed):
`subclass_of`, `instance_of`, `has_property`, `part_of`, `member_of`, `located_in`, `causes`, `precedes`, `related_to`, `synonym_of`, `defined_in`, `authored_by`.

When you introduce a new type, use it consistently for the rest of the run and note it in `meta`.

## Workflow: extracting an ontology from documents

### 1. Ingest

- `.txt` / `.md` → read with the Read tool.
- Binary (`.pdf`, `.docx`, `.pptx`, `.html`, ...) → convert to text first:

  ```bash
  python scripts/ingest.py path/to/doc.pdf > doc.md
  ```

  Or pipe multiple files into one stream:

  ```bash
  python scripts/ingest.py a.pdf b.docx c.md > corpus.md
  ```

  `ingest.py` requires `markitdown[all]`. If missing, tell the user:
  `pip install 'markitdown[all]'`.

### 2. Extract entities and relations

Read the ingested text and identify:

- **Named entities** (people, organizations, places, artifacts) → `Instance` nodes.
- **Types / categories / abstractions** → `Class` nodes.
- **Attributes that appear as standalone concepts** → `Property` nodes.
- **Relations between them** → edges with a clear `type`.

Quality guidelines:

- **Deduplicate aggressively.** `"dogs"`, `"Dog"`, `"the dog"` → one node `Dog`. Track surface variants in `props.aliases`.
- **Prefer specific edge types over `related_to`.** `related_to` is a fallback, not a default.
- **Anchor to sources.** Put the originating filename in `props.source` (and `props.page` for PDFs) so claims stay auditable.
- **Keep labels canonical.** Singular, titled for classes (`"Dog"`, not `"Dogs"`); natural case for instances (`"Rex"`, `"New York City"`).
- **Do not invent.** If a relation is not stated or strongly implied by the text, leave it out.

### 3. Build the ontology

Two styles — pick based on size.

**(a) Bulk write (fast, for first pass):** Assemble the full JSON in one shot and write it with the Write tool. Then validate:

```bash
python scripts/ontology.py -f ontology.json validate
```

**(b) Incremental (for edits and additions):** Use the CLI one call at a time.

```bash
python scripts/ontology.py -f ontology.json init --name my_ontology
python scripts/ontology.py -f ontology.json add-node --label "Dog" --type Class
python scripts/ontology.py -f ontology.json add-node --label "Mammal" --type Class
python scripts/ontology.py -f ontology.json add-edge --source Dog --target Mammal --type subclass_of
```

For a large corpus: bulk-write per document into a temp ontology, then `merge` into the main one.

### 4. Review

Always finish an extraction run with:

```bash
python scripts/ontology.py -f ontology.json stats
python scripts/ontology.py -f ontology.json validate
```

Report node/edge counts and any dangling references to the user. Ask before auto-fixing.

## Operations reference

All commands take `-f <path>` (defaults to `ontology.json`).

| Command | Purpose |
|---|---|
| `init [--name NAME]` | Create an empty ontology file. |
| `add-node --label L [--id ID] [--type T] [--props JSON] [--update]` | Add or update a node. |
| `add-edge --source S --target T --type R [--props JSON]` | Add a directed edge. |
| `remove-node ID` | Remove a node and every edge that touches it. |
| `remove-edge [--source S] [--target T] [--type R]` | Remove all edges matching the given filters (at least one required). |
| `search [QUERY] [--type T] [--edge-type R] [--source S] [--target T] [--json]` | Find nodes/edges by substring and/or type filters. |
| `traverse NODE [--direction in\|out] [--edge-type R] [--depth N] [--json]` | BFS from a node along edges of a given type/direction. |
| `merge OTHER [--overwrite]` | Merge `OTHER` ontology into `-f` file (dedupe nodes/edges, optionally overwrite on conflict). |
| `stats` | Node/edge counts, broken down by type. |
| `validate` | Check for duplicate IDs and dangling edge endpoints. |
| `export FORMAT [--out PATH]` | Export to `graphml`, `cypher`, `csv`, `svg`, or `mermaid`. |

### Common recipes

**List every subclass of `Mammal` (recursive):**
```bash
python scripts/ontology.py traverse Mammal --direction in --edge-type subclass_of
```
(Direction is `in` because edges are written `Dog -subclass_of-> Mammal`; subclasses point **to** `Mammal`.)

**List every instance of `Dog`:**
```bash
python scripts/ontology.py traverse Dog --direction in --edge-type instance_of --depth 1
```

**Find anything mentioning "protein":**
```bash
python scripts/ontology.py search protein
```

**Export for Neo4j:**
```bash
python scripts/ontology.py export cypher --out ontology.cypher
# then in cypher-shell:  :source ontology.cypher
```

**Export for Gephi / yEd:**
```bash
python scripts/ontology.py export graphml --out ontology.graphml
```

**Export node/edge CSV pair for Neo4j `LOAD CSV`:**
```bash
python scripts/ontology.py export csv --out ontology.csv
# produces ontology_nodes.csv and ontology_edges.csv with :ID / :START_ID / :END_ID headers
```

**Render a diagram as an SVG image (no external binary needed):**
```bash
python scripts/ontology.py export svg --out ontology.svg
# open ontology.svg in any browser or image viewer
```

**Render as Mermaid text (for GitHub / VS Code / Obsidian / Notion / mermaid.live):**
```bash
python scripts/ontology.py export mermaid --out ontology.mmd
# paste the contents into a ```mermaid fenced block, or open on mermaid.live
```

## Scripts in this skill

- `scripts/ontology.py` — stdlib-only CLI for all read/write/search/export operations. No install needed.
- `scripts/ingest.py` — thin wrapper around `markitdown[all]` for binary inputs.
