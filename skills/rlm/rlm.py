#!/usr/bin/env python3
"""Recursive Language Model orchestrator. See SKILL.md for usage."""
import re
import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tag definitions
# ---------------------------------------------------------------------------

@dataclass
class PeekTag:
    file: str
    start: int
    end: int


@dataclass
class RecurseTag:
    query: str
    file: str
    start: int
    end: int


@dataclass
class AnswerTag:
    content: str


_PEEK_RE    = re.compile(r'<peek\b([^>]*)/>', re.DOTALL)
_RECURSE_RE = re.compile(r'<recurse\b([^>]*)/>', re.DOTALL)
_ANSWER_RE  = re.compile(r'<answer>(.*?)</answer>', re.DOTALL)
_ATTR_RE    = re.compile(r'(\w+)="([^"]*)"')


def _attrs(s: str) -> dict:
    return dict(_ATTR_RE.findall(s))


def parse_tags(response: str) -> Union[PeekTag, RecurseTag, AnswerTag]:
    m = _ANSWER_RE.search(response)
    if m:
        return AnswerTag(content=m.group(1).strip())

    # When multiple action tags appear (unexpected), <peek> takes priority over <recurse>.
    # The LLM is instructed to emit only one tag per response (see prompt.py SYSTEM_PROMPT).
    m = _PEEK_RE.search(response)
    if m:
        a = _attrs(m.group(1))
        if "file" in a and "lines" in a:
            parts = a["lines"].split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                s, e = int(parts[0]), int(parts[1])
                if s <= e:
                    return PeekTag(file=a["file"], start=s, end=e)

    m = _RECURSE_RE.search(response)
    if m:
        a = _attrs(m.group(1))
        if "query" in a and "file" in a and "lines" in a:
            parts = a["lines"].split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                s, e = int(parts[0]), int(parts[1])
                if s <= e:
                    return RecurseTag(
                        query=a["query"], file=a["file"],
                        start=s, end=e
                    )

    return AnswerTag(content=response.strip())


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------

Manifest = Dict[str, Tuple[int, int]]


def _count_lines(path: Path) -> int:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _matches(rel: str, patterns: Optional[List[str]]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(rel, p) for p in patterns)


def build_manifest(
    input_path: str,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> Manifest:
    p = Path(input_path)
    if p.is_file():
        n = _count_lines(p)
        return {str(p): (1, n)} if n > 0 else {}

    manifest: Manifest = {}
    for root, dirs, files in os.walk(p):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(p))
            if exclude and _matches(rel, exclude):
                continue
            if not _matches(rel, include):
                continue
            n = _count_lines(fpath)
            if n > 0:
                manifest[str(fpath)] = (1, n)
    return manifest
