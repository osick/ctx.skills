#!/usr/bin/env python3
"""Recursive Language Model orchestrator. See SKILL.md for usage."""
import re
from dataclasses import dataclass
from typing import Union


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

    m = _PEEK_RE.search(response)
    if m:
        a = _attrs(m.group(1))
        if "file" in a and "lines" in a:
            parts = a["lines"].split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return PeekTag(file=a["file"], start=int(parts[0]), end=int(parts[1]))

    m = _RECURSE_RE.search(response)
    if m:
        a = _attrs(m.group(1))
        if "query" in a and "file" in a and "lines" in a:
            parts = a["lines"].split("-")
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                return RecurseTag(
                    query=a["query"], file=a["file"],
                    start=int(parts[0]), end=int(parts[1])
                )

    return AnswerTag(content=response.strip())
