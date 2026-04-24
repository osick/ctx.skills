#!/usr/bin/env python3
"""Convert text/binary documents to plain text for ontology extraction.

Usage:
    python ingest.py file1 [file2 ...]           # prints concatenated text to stdout
    python ingest.py --out corpus.md file1 ...   # writes to a single file

.txt and .md are read verbatim. Everything else is routed through
markitdown[all]  (install: pip install 'markitdown[all]').
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".markdown", ".rst"}


def convert(path: Path) -> str:
    if path.suffix.lower() in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        from markitdown import MarkItDown  # type: ignore
    except ImportError:
        sys.exit(
            "markitdown is required for non-text files.\n"
            "install it with:  pip install 'markitdown[all]'"
        )
    md = MarkItDown()
    result = md.convert(str(path))
    return getattr(result, "text_content", "") or ""


def main():
    ap = argparse.ArgumentParser(description="Convert documents to text for ontology extraction.")
    ap.add_argument("files", nargs="+", help="input files (.txt, .md, .pdf, .docx, .pptx, .html, ...)")
    ap.add_argument("--out", help="write combined output to this file (default: stdout)")
    ap.add_argument("--no-header", action="store_true", help="do not emit '=== <filename> ===' headers")
    args = ap.parse_args()

    chunks = []
    for fp in args.files:
        p = Path(fp)
        if not p.exists():
            print(f"# [missing: {fp}]", file=sys.stderr)
            continue
        try:
            text = convert(p)
        except Exception as e:
            print(f"# [error converting {fp}: {e}]", file=sys.stderr)
            continue
        if args.no_header:
            chunks.append(text)
        else:
            chunks.append(f"=== {p.name} ===\n\n{text}")

    combined = "\n\n".join(chunks)
    if args.out:
        Path(args.out).write_text(combined, encoding="utf-8")
        print(f"wrote {args.out}  ({len(combined):,} chars from {len(chunks)} file(s))", file=sys.stderr)
    else:
        sys.stdout.write(combined)


if __name__ == "__main__":
    main()
