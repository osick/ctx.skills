#!/usr/bin/env python3
"""Recursive Language Model orchestrator. See SKILL.md for usage."""
import re
import fnmatch
import os
import subprocess
import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Union, Dict, List, Optional, Tuple
_SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


def build_prompt(query: str, manifest: dict, context_items: list = None) -> str:
    manifest_text = "\n".join(
        f"{path}    lines {start}-{end}"
        for path, (start, end) in manifest.items()
    )
    prompt = f"{_SYSTEM_PROMPT}\n## Manifest\n\n{manifest_text}\n\n## Query\n\n{query}"
    if context_items:
        prompt += "\n\n## Context gathered so far\n\n" + "\n\n---\n\n".join(context_items)
    return prompt


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
    # The LLM is instructed to emit only one tag per response (see system_prompt.txt).
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


# NOTE: Pattern matching uses fnmatch which treats '/' as a regular character.
# '*.py' matches at any depth (e.g., 'src/auth/login.py') because '*' absorbs slashes.
# 'tests/*' only covers one directory level — 'tests/sub/foo.py' is NOT excluded.
# '**' glob syntax is NOT supported. Use patterns without slashes for depth-independent matching.
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
        # Single-file input: include/exclude filters do not apply.
        # The caller explicitly selected this file, so it is always included.
        n = _count_lines(p)
        return {str(p): (1, n)} if n > 0 else {}

    manifest: Manifest = {}
    for root, dirs, files in os.walk(p):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(p))
            # Guard needed: _matches(rel, None) returns True, which would exclude everything.
            if exclude and _matches(rel, exclude):
                continue
            if not _matches(rel, include):
                continue
            n = _count_lines(fpath)
            if n > 0:
                manifest[str(fpath)] = (1, n)
    return manifest


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def peek_lines(filepath: str, start: int, end: int) -> str:
    lines = []
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, 1):
                if i > end:
                    break
                if i >= start:
                    lines.append(f"{i}: {line}")
    except OSError as e:
        return f"[Error reading {filepath}: {e}]"
    return "".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_llm(prompt: str, llm_cmd: str) -> str:
    result = subprocess.run(
        llm_cmd, shell=True, input=prompt, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LLM command failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Core recursion loop
# ---------------------------------------------------------------------------

def rlm(
    query: str,
    manifest: "Manifest",
    llm_cmd: str,
    max_depth: int,
    max_turns: int,
    _depth: int = 0,
    _calls: Optional[List[int]] = None,
) -> str:
    if _calls is None:
        _calls = [0]

    if _depth > max_depth:
        return f"[Max recursion depth {max_depth} reached]"

    context_items: List[str] = []

    for _ in range(max_turns):
        _calls[0] += 1
        if _calls[0] > max_depth * max_turns * 2:  # global call budget
            return f"[Global call budget ({max_depth * max_turns * 2}) exhausted]"
        prompt = build_prompt(query, manifest, context_items or None)
        response = call_llm(prompt, llm_cmd)
        tag = parse_tags(response)

        if isinstance(tag, AnswerTag):
            return tag.content

        if isinstance(tag, PeekTag):
            content = peek_lines(tag.file, tag.start, tag.end)
            context_items.append(
                f"[peek {tag.file} lines {tag.start}-{tag.end}]\n{content}"
            )
        elif isinstance(tag, RecurseTag):
            sub_manifest: Manifest = {tag.file: (tag.start, tag.end)}
            sub_result = rlm(
                tag.query, sub_manifest, llm_cmd,
                max_depth, max_turns, _depth + 1, _calls
            )
            context_items.append(f"[sub-query: {tag.query}]\n{sub_result}")

    return context_items[-1] if context_items else "[No answer produced within turn limit]"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursive Language Model — process large inputs with any LLM"
    )
    parser.add_argument("--query",     required=True, help="Question to answer")
    parser.add_argument("--input",     required=True, help="File, directory, or - for stdin")
    parser.add_argument("--llm-cmd",   required=True, dest="llm_cmd",
                        help="Shell command: reads prompt from stdin, writes answer to stdout")
    parser.add_argument("--max-depth", type=int, default=4,  dest="max_depth")
    parser.add_argument("--max-turns", type=int, default=10, dest="max_turns")
    parser.add_argument("--include",   action="append", metavar="GLOB",
                        help="Include only files matching glob (repeatable)")
    parser.add_argument("--exclude",   action="append", metavar="GLOB",
                        help="Exclude files matching glob (repeatable)")
    args = parser.parse_args()

    tmp = None
    if args.input == "-":
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        tmp.write(sys.stdin.read())
        tmp.close()
        input_path = tmp.name
    else:
        input_path = args.input

    try:
        manifest = build_manifest(input_path, args.include, args.exclude)
        if not manifest:
            sys.exit("No files found matching the given input and filters.")
        result = rlm(args.query, manifest, args.llm_cmd, args.max_depth, args.max_turns)
        print(result)
    finally:
        if tmp:
            os.unlink(tmp.name)


if __name__ == "__main__":
    main()
