#!/usr/bin/env python3
"""Ontology CLI: create, edit, search, traverse, merge, export.

Storage: a single JSON file (ontology.json) with shape:
    {"meta": {...}, "nodes": [...], "edges": [...]}

Stdlib only. Python 3.8+.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path


# ---------- persistence ----------

def _empty(name: str = "ontology") -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "meta": {"name": name, "created": now, "updated": now, "sources": []},
        "nodes": [],
        "edges": [],
    }


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return _empty()
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("meta", {})
    data.setdefault("nodes", [])
    data.setdefault("edges", [])
    return data


def save(path: str, onto: dict) -> None:
    onto.setdefault("meta", {})
    onto["meta"]["updated"] = datetime.now(timezone.utc).isoformat()
    Path(path).write_text(
        json.dumps(onto, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# German diacritics get expanded to two-letter equivalents BEFORE NFKD,
# because NFKD alone would strip the umlaut diacritic and produce
# "Muenchen" -> "Munchen" which is wrong in German.
_GERMAN_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss", "ẞ": "SS",
})


def slug(s: str) -> str:
    """Deterministic slug used for node IDs.

    Pipeline (must match the description in SKILL.md):
      1. German diacritics map to two-letter equivalents (ä->ae, ö->oe, ü->ue, ß->ss).
      2. Unicode NFKD strips remaining combining marks (é->e, ç->c, ñ->n, ...).
      3. Any run of characters outside [A-Za-z0-9_] becomes a single underscore.
      4. Leading/trailing underscores trimmed. Fallback "node" if empty.
    """
    s = str(s).translate(_GERMAN_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")
    return s or "node"


def parse_props(raw):
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"--props must be JSON: {e}")
    if not isinstance(d, dict):
        sys.exit("--props must be a JSON object")
    return d


# ---------- commands ----------

def cmd_init(args):
    onto = _empty(args.name or "ontology")
    save(args.file, onto)
    print(f"initialized {args.file}")


def cmd_add_node(args):
    onto = load(args.file)
    node_id = args.id or slug(args.label)
    idx = next((i for i, n in enumerate(onto["nodes"]) if n["id"] == node_id), -1)
    props = parse_props(args.props)
    if idx >= 0:
        if not args.update:
            sys.exit(f"node exists: {node_id} (pass --update to modify)")
        n = onto["nodes"][idx]
        if args.type:
            n["type"] = args.type
        if args.label:
            n["label"] = args.label
        if props:
            n.setdefault("props", {}).update(props)
        action = "updated"
    else:
        n = {"id": node_id, "type": args.type or "Entity", "label": args.label}
        if props:
            n["props"] = props
        onto["nodes"].append(n)
        action = "added"
    save(args.file, onto)
    print(f"{action} {node_id}")


def cmd_add_edge(args):
    onto = load(args.file)
    ids = {n["id"] for n in onto["nodes"]}
    if args.source not in ids:
        sys.exit(f"unknown source node: {args.source}")
    if args.target not in ids:
        sys.exit(f"unknown target node: {args.target}")
    edge = {"source": args.source, "target": args.target, "type": args.type}
    props = parse_props(args.props)
    if props:
        edge["props"] = props
    for e in onto["edges"]:
        if (
            e["source"] == edge["source"]
            and e["target"] == edge["target"]
            and e["type"] == edge["type"]
        ):
            print("edge exists, skipping", file=sys.stderr)
            return
    onto["edges"].append(edge)
    save(args.file, onto)
    print(f"added {args.source} -[{args.type}]-> {args.target}")


def cmd_remove_node(args):
    onto = load(args.file)
    n0, e0 = len(onto["nodes"]), len(onto["edges"])
    onto["nodes"] = [n for n in onto["nodes"] if n["id"] != args.id]
    onto["edges"] = [
        e for e in onto["edges"] if e["source"] != args.id and e["target"] != args.id
    ]
    save(args.file, onto)
    print(f"removed {n0 - len(onto['nodes'])} node(s), {e0 - len(onto['edges'])} edge(s)")


def cmd_remove_edge(args):
    if not (args.source or args.target or args.type):
        sys.exit("remove-edge needs at least one of --source, --target, --type")
    onto = load(args.file)
    before = len(onto["edges"])

    def matches(e):
        if args.source and e["source"] != args.source:
            return False
        if args.target and e["target"] != args.target:
            return False
        if args.type and e["type"] != args.type:
            return False
        return True

    onto["edges"] = [e for e in onto["edges"] if not matches(e)]
    save(args.file, onto)
    print(f"removed {before - len(onto['edges'])} edge(s)")


def cmd_search(args):
    onto = load(args.file)
    q = args.query.lower() if args.query else None
    out_nodes, out_edges = [], []

    for n in onto["nodes"]:
        if args.type and n.get("type") != args.type:
            continue
        if q:
            hay = " ".join([
                n.get("id", ""),
                n.get("label", ""),
                n.get("type", ""),
                json.dumps(n.get("props", {}), ensure_ascii=False),
            ]).lower()
            if q not in hay:
                continue
        out_nodes.append(n)

    for e in onto["edges"]:
        if args.edge_type and e.get("type") != args.edge_type:
            continue
        if args.source and e["source"] != args.source:
            continue
        if args.target and e["target"] != args.target:
            continue
        if q:
            hay = " ".join([
                e["source"], e["target"], e["type"],
                json.dumps(e.get("props", {}), ensure_ascii=False),
            ]).lower()
            if q not in hay:
                continue
        out_edges.append(e)

    if args.json:
        print(json.dumps({"nodes": out_nodes, "edges": out_edges}, indent=2, ensure_ascii=False))
        return
    for n in out_nodes:
        print(f"NODE  {n['id']:<30} [{n.get('type','')}]  {n.get('label','')}")
    for e in out_edges:
        print(f"EDGE  {e['source']} -[{e['type']}]-> {e['target']}")
    if not out_nodes and not out_edges:
        print("(no matches)")


def cmd_traverse(args):
    onto = load(args.file)
    by_id = {n["id"]: n for n in onto["nodes"]}
    if args.node not in by_id:
        sys.exit(f"unknown node: {args.node}")

    out_adj: dict = {}
    in_adj: dict = {}
    for e in onto["edges"]:
        if args.edge_type and e["type"] != args.edge_type:
            continue
        out_adj.setdefault(e["source"], []).append((e["target"], e["type"]))
        in_adj.setdefault(e["target"], []).append((e["source"], e["type"]))

    def step(nid):
        if args.direction == "out":
            return out_adj.get(nid, [])
        if args.direction == "in":
            return in_adj.get(nid, [])
        return out_adj.get(nid, []) + in_adj.get(nid, [])

    visited = {args.node}
    q = deque([(args.node, 0)])
    results = []
    while q:
        cur, depth = q.popleft()
        if args.depth is not None and depth >= args.depth:
            continue
        for nxt, etype in step(cur):
            if nxt in visited:
                continue
            visited.add(nxt)
            results.append({"id": nxt, "depth": depth + 1, "via": etype, "from": cur})
            q.append((nxt, depth + 1))

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    for r in results:
        label = by_id.get(r["id"], {}).get("label", r["id"])
        indent = "  " * (r["depth"] - 1)
        print(f"{indent}{r['id']}  ({label})  via {r['via']} from {r['from']}")
    if not results:
        print("(no reachable nodes)")


def cmd_merge(args):
    a = load(args.file)
    b = load(args.other)
    existing = {n["id"]: n for n in a["nodes"]}
    conflicts = []
    for n in b["nodes"]:
        if n["id"] in existing:
            if existing[n["id"]] != n:
                conflicts.append(n["id"])
                if args.overwrite:
                    existing[n["id"]] = n
        else:
            existing[n["id"]] = n
    a["nodes"] = list(existing.values())

    edge_keys = {(e["source"], e["target"], e["type"]): e for e in a["edges"]}
    for e in b["edges"]:
        k = (e["source"], e["target"], e["type"])
        if k not in edge_keys:
            edge_keys[k] = e
    a["edges"] = list(edge_keys.values())

    srcs = a.setdefault("meta", {}).setdefault("sources", [])
    for s in b.get("meta", {}).get("sources", []):
        if s not in srcs:
            srcs.append(s)

    save(args.file, a)
    print(f"merged. nodes={len(a['nodes'])} edges={len(a['edges'])} conflicts={len(conflicts)}")
    for c in conflicts:
        print(f"  conflict on node: {c}" + ("  [overwritten]" if args.overwrite else "  [kept original]"))


def cmd_stats(args):
    onto = load(args.file)
    node_types = Counter(n.get("type", "?") for n in onto["nodes"])
    edge_types = Counter(e.get("type", "?") for e in onto["edges"])
    print(f"file:    {args.file}")
    print(f"name:    {onto.get('meta', {}).get('name', '(none)')}")
    print(f"sources: {len(onto.get('meta', {}).get('sources', []))}")
    print(f"nodes:   {len(onto['nodes'])}")
    for t, c in node_types.most_common():
        print(f"  {t}: {c}")
    print(f"edges:   {len(onto['edges'])}")
    for t, c in edge_types.most_common():
        print(f"  {t}: {c}")


def cmd_validate(args):
    onto = load(args.file)
    errors = []
    seen = set()
    for n in onto["nodes"]:
        if "id" not in n:
            errors.append(f"node missing id: {n}")
            continue
        if n["id"] in seen:
            errors.append(f"duplicate node id: {n['id']}")
        seen.add(n["id"])
        if "label" not in n:
            errors.append(f"node missing label: {n['id']}")
    for e in onto["edges"]:
        for k in ("source", "target", "type"):
            if k not in e:
                errors.append(f"edge missing {k}: {e}")
                break
        else:
            if e["source"] not in seen:
                errors.append(f"dangling source: {e['source']} -[{e['type']}]-> {e['target']}")
            if e["target"] not in seen:
                errors.append(f"dangling target: {e['source']} -[{e['type']}]-> {e['target']}")
    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        sys.exit(1)
    print(f"ok. {len(onto['nodes'])} nodes, {len(onto['edges'])} edges.")


# ---------- export ----------

def _xml(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _cy(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def export_graphml(onto, out):
    prop_keys = set()
    for n in onto["nodes"]:
        prop_keys.update((n.get("props") or {}).keys())
    edge_prop_keys = set()
    for e in onto["edges"]:
        edge_prop_keys.update((e.get("props") or {}).keys())

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<graphml xmlns="http://graphml.graphdrawing.org/xmlns">')
    lines.append('  <key id="label" for="node" attr.name="label" attr.type="string"/>')
    lines.append('  <key id="type" for="node" attr.name="type" attr.type="string"/>')
    for k in sorted(prop_keys):
        lines.append(f'  <key id="np_{_xml(k)}" for="node" attr.name="{_xml(k)}" attr.type="string"/>')
    lines.append('  <key id="etype" for="edge" attr.name="type" attr.type="string"/>')
    for k in sorted(edge_prop_keys):
        lines.append(f'  <key id="ep_{_xml(k)}" for="edge" attr.name="{_xml(k)}" attr.type="string"/>')
    lines.append('  <graph id="G" edgedefault="directed">')

    for n in onto["nodes"]:
        lines.append(f'    <node id="{_xml(n["id"])}">')
        lines.append(f'      <data key="label">{_xml(n.get("label",""))}</data>')
        lines.append(f'      <data key="type">{_xml(n.get("type",""))}</data>')
        for k, v in (n.get("props") or {}).items():
            lines.append(f'      <data key="np_{_xml(k)}">{_xml(v)}</data>')
        lines.append("    </node>")

    for i, e in enumerate(onto["edges"]):
        lines.append(
            f'    <edge id="e{i}" source="{_xml(e["source"])}" target="{_xml(e["target"])}">'
        )
        lines.append(f'      <data key="etype">{_xml(e["type"])}</data>')
        for k, v in (e.get("props") or {}).items():
            lines.append(f'      <data key="ep_{_xml(k)}">{_xml(v)}</data>')
        lines.append("    </edge>")

    lines.append("  </graph>")
    lines.append("</graphml>")
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def export_cypher(onto, out):
    lines = ["// generated by ontology skill"]
    for n in onto["nodes"]:
        t = re.sub(r"\W", "", n.get("type") or "") or "Entity"
        props = {"id": n["id"], "label": n.get("label", n["id"])}
        props.update(n.get("props") or {})
        body = ", ".join(f"{k}: '{_cy(v)}'" for k, v in props.items())
        lines.append(f"MERGE (:{t} {{{body}}});")
    for e in onto["edges"]:
        rel = re.sub(r"\W", "_", e["type"]).upper() or "REL"
        extra = ""
        if e.get("props"):
            extra = " " + "{" + ", ".join(f"{k}: '{_cy(v)}'" for k, v in e["props"].items()) + "}"
        lines.append(
            f"MATCH (a {{id: '{_cy(e['source'])}'}}), (b {{id: '{_cy(e['target'])}'}}) "
            f"MERGE (a)-[:{rel}{extra}]->(b);"
        )
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def export_csv(onto, out):
    base = Path(out)
    if base.suffix.lower() == ".csv":
        nodes_path = base.with_name(base.stem + "_nodes.csv")
        edges_path = base.with_name(base.stem + "_edges.csv")
    else:
        base.mkdir(parents=True, exist_ok=True)
        nodes_path = base / "nodes.csv"
        edges_path = base / "edges.csv"

    node_prop_keys = sorted({k for n in onto["nodes"] for k in (n.get("props") or {})})
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id:ID", "label", ":LABEL"] + node_prop_keys)
        for n in onto["nodes"]:
            props = n.get("props") or {}
            w.writerow(
                [n["id"], n.get("label", ""), n.get("type", "")]
                + [props.get(k, "") for k in node_prop_keys]
            )

    edge_prop_keys = sorted({k for e in onto["edges"] for k in (e.get("props") or {})})
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([":START_ID", ":END_ID", ":TYPE"] + edge_prop_keys)
        for e in onto["edges"]:
            props = e.get("props") or {}
            w.writerow(
                [e["source"], e["target"], e["type"]]
                + [props.get(k, "") for k in edge_prop_keys]
            )
    print(f"wrote {nodes_path} and {edges_path}", file=sys.stderr)


_HIER_EDGES = {"subclass_of", "instance_of", "part_of", "member_of"}

_NODE_COLORS = {
    "Class": "#cfe8ff",
    "Instance": "#ffedcc",
    "Person": "#ffd6d6",
    "Organization": "#e3d6ff",
    "Location": "#d6ffd6",
    "Property": "#f2f2f2",
    "Event": "#fff0cc",
    "Process": "#fff0cc",
    "Document": "#e6e6fa",
    "Artifact": "#e6e6fa",
    "Concept": "#f8f8f8",
}


def _layered_layout(nodes, edges):
    """Assign (x, y) to each node using a simple Sugiyama-style layered layout.

    Returns (positions, svg_width, svg_height, node_width, node_height).
    Nodes are laid out top-to-bottom by hierarchy depth (roots on top).
    """
    ids = [n["id"] for n in nodes]
    id_set = set(ids)
    parents = {nid: [] for nid in ids}
    for e in edges:
        if e["type"] in _HIER_EDGES and e["source"] in id_set and e["target"] in id_set:
            parents[e["source"]].append(e["target"])

    level = {}

    def compute_level(nid, stack):
        if nid in level:
            return level[nid]
        if nid in stack:
            return 0
        stack.add(nid)
        ps = parents.get(nid, [])
        lv = 1 + max((compute_level(p, stack) for p in ps), default=-1)
        stack.discard(nid)
        level[nid] = lv
        return lv

    for nid in ids:
        compute_level(nid, set())

    by_level = {}
    for nid, lv in level.items():
        by_level.setdefault(lv, []).append(nid)

    node_w, node_h = 180, 56
    x_gap, y_gap = 40, 90

    positions = {}
    max_row = 0
    for lv, members in by_level.items():
        members.sort()
        max_row = max(max_row, len(members))
        for i, nid in enumerate(members):
            positions[nid] = (i * (node_w + x_gap) + 40, lv * (node_h + y_gap) + 40)

    total_w = max(max_row * (node_w + x_gap) + 40, 400)
    total_h = (max(by_level) + 1) * (node_h + y_gap) + 40 if by_level else 200
    return positions, total_w, total_h, node_w, node_h


def export_svg(onto, out):
    positions, W, H, NW, NH = _layered_layout(onto["nodes"], onto["edges"])
    nodes_by_id = {n["id"]: n for n in onto["nodes"]}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="system-ui, -apple-system, sans-serif" font-size="12">',
        "<defs>",
        '  <marker id="arr" viewBox="0 0 10 10" refX="10" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#666"/></marker>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="white"/>',
    ]

    for e in onto["edges"]:
        if e["source"] not in positions or e["target"] not in positions:
            continue
        x1, y1 = positions[e["source"]]
        x2, y2 = positions[e["target"]]
        cx1, cy1 = x1 + NW / 2, y1 + NH / 2
        cx2, cy2 = x2 + NW / 2, y2 + NH / 2
        dx, dy = cx2 - cx1, cy2 - cy1
        dist = math.hypot(dx, dy) or 1.0
        ux, uy = dx / dist, dy / dist
        sx = cx1 + ux * (NH / 2 + 2)
        sy = cy1 + uy * (NH / 2 + 2)
        ex = cx2 - ux * (NH / 2 + 6)
        ey = cy2 - uy * (NH / 2 + 6)
        parts.append(
            f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="#666" stroke-width="1.2" marker-end="url(#arr)"/>'
        )
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        parts.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" fill="#444" '
            f'stroke="white" stroke-width="3" paint-order="stroke" font-size="11">'
            f"{_xml(e['type'])}</text>"
        )

    for nid, (x, y) in positions.items():
        n = nodes_by_id[nid]
        label = n.get("label", nid)
        t = n.get("type", "")
        color = _NODE_COLORS.get(t, "#f8f8f8")
        parts.append(
            f'<g><rect x="{x}" y="{y}" width="{NW}" height="{NH}" rx="8" ry="8" '
            f'fill="{color}" stroke="#333" stroke-width="1.2"/>'
            f'<text x="{x + NW / 2}" y="{y + NH / 2 - 2}" text-anchor="middle" font-weight="600">'
            f"{_xml(label)}</text>"
            f'<text x="{x + NW / 2}" y="{y + NH / 2 + 14}" text-anchor="middle" '
            f'font-size="10" fill="#555">[{_xml(t)}]</text></g>'
        )

    parts.append("</svg>")
    Path(out).write_text("\n".join(parts), encoding="utf-8")


def _mermaid_id(s):
    safe = re.sub(r"[^A-Za-z0-9_]", "_", str(s))
    if not safe or safe[0].isdigit():
        safe = "n_" + safe
    return safe


def export_mermaid(onto, out):
    lines = ["graph LR"]
    for n in onto["nodes"]:
        mid = _mermaid_id(n["id"])
        label = (
            str(n.get("label", n["id"]))
            .replace('"', "&quot;")
            .replace("[", "(")
            .replace("]", ")")
        )
        t = n.get("type", "")
        if t:
            lines.append(f'  {mid}["{label}<br/><i>{t}</i>"]')
        else:
            lines.append(f'  {mid}["{label}"]')
    for e in onto["edges"]:
        src = _mermaid_id(e["source"])
        tgt = _mermaid_id(e["target"])
        etype = str(e["type"]).replace("|", "/")
        lines.append(f"  {src} -->|{etype}| {tgt}")
    Path(out).write_text("\n".join(lines), encoding="utf-8")


def cmd_export(args):
    onto = load(args.file)
    fmt = args.format
    default_ext = {
        "graphml": "graphml",
        "cypher": "cypher",
        "csv": "csv",
        "svg": "svg",
        "mermaid": "mmd",
    }[fmt]
    out = args.out or f"ontology.{default_ext}"
    if fmt == "graphml":
        export_graphml(onto, out)
    elif fmt == "cypher":
        export_cypher(onto, out)
    elif fmt == "csv":
        export_csv(onto, out)
    elif fmt == "svg":
        export_svg(onto, out)
    elif fmt == "mermaid":
        export_mermaid(onto, out)
    print(f"wrote {out}")


# ---------- entrypoint ----------

def build_parser():
    p = argparse.ArgumentParser(prog="ontology", description="Ontology CLI (JSON-backed).")
    p.add_argument("-f", "--file", default="ontology.json", help="path to ontology.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create empty ontology file")
    s.add_argument("--name")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("add-node", help="add or update a node")
    s.add_argument("--id")
    s.add_argument("--label", required=True)
    s.add_argument("--type")
    s.add_argument("--props", help="JSON object of extra properties")
    s.add_argument("--update", action="store_true", help="update instead of erroring if node exists")
    s.set_defaults(func=cmd_add_node)

    s = sub.add_parser("add-edge", help="add a directed edge")
    s.add_argument("--source", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--type", required=True)
    s.add_argument("--props", help="JSON object of extra properties")
    s.set_defaults(func=cmd_add_edge)

    s = sub.add_parser("remove-node", help="remove a node and incident edges")
    s.add_argument("id")
    s.set_defaults(func=cmd_remove_node)

    s = sub.add_parser("remove-edge", help="remove edges matching filters")
    s.add_argument("--source")
    s.add_argument("--target")
    s.add_argument("--type")
    s.set_defaults(func=cmd_remove_edge)

    s = sub.add_parser("search", help="search nodes and edges")
    s.add_argument("query", nargs="?")
    s.add_argument("--type", help="filter nodes by type")
    s.add_argument("--edge-type", help="filter edges by type")
    s.add_argument("--source")
    s.add_argument("--target")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("traverse", help="BFS from a node")
    s.add_argument("node")
    s.add_argument("--direction", choices=["in", "out", "both"], default="out")
    s.add_argument("--edge-type")
    s.add_argument("--depth", type=int)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_traverse)

    s = sub.add_parser("merge", help="merge another ontology into -f")
    s.add_argument("other")
    s.add_argument("--overwrite", action="store_true")
    s.set_defaults(func=cmd_merge)

    s = sub.add_parser("stats", help="node/edge counts by type")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("validate", help="check structural integrity")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("export", help="export to graphml / cypher / csv / svg / mermaid")
    s.add_argument("format", choices=["graphml", "cypher", "csv", "svg", "mermaid"])
    s.add_argument("--out")
    s.set_defaults(func=cmd_export)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
