#!/usr/bin/env python3
"""NIAH Benchmark Runner — generate, test (direct LLM vs RLM), and evaluate.

Wraps the full cycle:
  1. Generate a NIAH sandbox with needles
  2. Run the question through an LLM in direct mode and/or via RLM
  3. Score the response against the expected answer
  4. Record timing, token count, and quality metrics

Usage:
    # Single run, direct mode
    python benchmark.py --size 5000 --needle-type retrieval --seed 1 \
        --mode direct --llm-cmd "claude -p" --results results.json

    # Compare direct vs RLM with different models
    python benchmark.py --size 10000 --needle-type reasoning --seed 1 \
        --mode both --llm-cmd-direct "claude -p --model sonnet" \
        --llm-cmd-rlm "claude -p --model haiku" --results results.json

    # Same model for both (--llm-cmd is the default for both modes)
    python benchmark.py --size 10000 --needle-type reasoning --seed 1 \
        --mode both --llm-cmd "claude -p" --results results.json

    # Sweep multiple seeds
    python benchmark.py --size 5000 --needle-type counting --seeds 1,2,3,4,5 \
        --mode both --llm-cmd "claude -p" --results results.json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Import generator from same directory
sys.path.insert(0, os.path.dirname(__file__))
from generate_context import generate_needle_context, write_sandbox


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_answer(actual: str, expected, needle_type: str) -> float:
    """Score an LLM response against the expected answer.

    Returns a float between 0.0 and 1.0.

    Scoring rules by needle type:
      retrieval / reasoning: 1.0 if expected string is found in the response
                             (case-insensitive), 0.0 otherwise.
      counting: fraction of expected counts found in the response.
    """
    actual_lower = actual.strip().lower()

    if needle_type == "counting":
        if not isinstance(expected, list):
            expected = [expected]
        found = 0
        for count in expected:
            if str(count) in actual_lower:
                found += 1
        return found / len(expected) if expected else 0.0

    # retrieval / reasoning — check if expected string appears in response
    expected_lower = str(expected).strip().lower()
    if expected_lower in actual_lower:
        return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

def make_result(
    mode: str,
    needle_type: str,
    size: int,
    seed: int,
    expected,
    actual: str,
    score: float,
    elapsed: float,
    token_count: int,
    llm_cmd: str = "",
) -> dict:
    return {
        "mode": mode,
        "needle_type": needle_type,
        "size": size,
        "seed": seed,
        "expected": expected,
        "actual": actual,
        "score": score,
        "elapsed_seconds": round(elapsed, 3),
        "token_count": token_count,
        "llm_cmd": llm_cmd,
    }


# ---------------------------------------------------------------------------
# LLM runners
# ---------------------------------------------------------------------------

def _run_direct(question: str, sandbox_dir: str, llm_cmd: str) -> tuple[str, float]:
    """Run the LLM in the sandbox directory and let it read the files itself.

    Creates a combined context.txt from all chunk files, then launches the LLM
    with cwd set to the sandbox directory.  The prompt instructs the LLM to
    read the files rather than piping the full context through stdin.

    Returns (response, elapsed_seconds).
    """
    sb = Path(sandbox_dir) / "sandbox"

    # Concatenate all chunks into a single context.txt for convenience
    chunks = []
    for f in sorted(sb.glob("chunk_*.txt")):
        chunks.append(f.read_text(encoding="utf-8"))
    combined = "\n".join(chunks)
    (sb / "context.txt").write_text(combined, encoding="utf-8")

    prompt = (
        f"You are in a directory that contains text files with context information.\n"
        f"Read the file 'context.txt' (or the individual chunk_*.txt files) "
        f"and answer the following question.\n\n"
        f"Question: {question}\n\n"
        f"Answer concisely."
    )

    start = time.monotonic()
    result = subprocess.run(
        llm_cmd, shell=True, input=prompt,
        capture_output=True, text=True,
        cwd=str(sb),
    )
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        return f"[LLM error: {result.stderr.strip()[:2000]}]", elapsed
    return result.stdout.strip(), elapsed


_RLM_SEGMENTS = 20       # number of segment files for RLM manifest
_WORDS_PER_LINE = 80     # words per line within each segment


def _prepare_rlm_input(sandbox_dir: str) -> str:
    """Split chunk files into a handful of segment files for RLM processing.

    With many small chunk files (e.g. 4000 for a 2M-token context) the RLM
    manifest becomes huge and overwhelms smaller models.  A single merged
    file is too opaque — the model has no structure to guide its search.

    Instead, we create ~20 segment files with ~80 words per line.  This gives
    the RLM manifest enough structure (file names with numbered ranges) for
    the model to make informed peek/recurse decisions while keeping the
    manifest compact.

    Returns the path to the segment directory.
    """
    sb = Path(sandbox_dir) / "sandbox"
    seg_dir = sb / "segments"

    # If already created, skip
    if seg_dir.exists():
        return str(seg_dir)
    seg_dir.mkdir()

    # Collect all words from chunks
    words: list[str] = []
    for f in sorted(sb.glob("chunk_*.txt")):
        words.extend(f.read_text(encoding="utf-8").split())

    # Split into segments, each with multi-line content
    total = len(words)
    words_per_seg = max(1, total // _RLM_SEGMENTS)

    for seg_idx in range(_RLM_SEGMENTS):
        start = seg_idx * words_per_seg
        end = start + words_per_seg if seg_idx < _RLM_SEGMENTS - 1 else total
        seg_words = words[start:end]
        if not seg_words:
            break

        lines: list[str] = []
        for i in range(0, len(seg_words), _WORDS_PER_LINE):
            lines.append(" ".join(seg_words[i : i + _WORDS_PER_LINE]))

        (seg_dir / f"segment_{seg_idx:02d}.txt").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    return str(seg_dir)


def _run_rlm(question: str, sandbox_dir: str, llm_cmd: str) -> tuple[str, float]:
    """Run the question through the RLM skill.

    Returns (response, elapsed_seconds).
    """
    rlm_script = os.path.join(
        os.path.dirname(__file__), "..", "..", "skills", "rlm", "rlm.py"
    )
    rlm_script = os.path.normpath(rlm_script)

    seg_dir = _prepare_rlm_input(sandbox_dir)

    cmd = [
        sys.executable, rlm_script,
        "--query", question,
        "--input", seg_dir,
        "--llm-cmd", llm_cmd,
    ]

    start = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        return f"[RLM error: {result.stderr.strip()[:2000]}]", elapsed
    return result.stdout.strip(), elapsed


# ---------------------------------------------------------------------------
# Single benchmark run
# ---------------------------------------------------------------------------

def run_benchmark(
    size: int,
    needle_type: str,
    seed: int,
    mode: str,
    llm_cmd: str,
    llm_cmd_direct: Optional[str] = None,
    llm_cmd_rlm: Optional[str] = None,
) -> list[dict]:
    """Run one or two benchmark trials (direct and/or rlm).

    Args:
        llm_cmd: Default LLM command used for both modes.
        llm_cmd_direct: Override LLM command for direct mode (optional).
        llm_cmd_rlm: Override LLM command for RLM mode (optional).

    Returns a list of result dicts.
    """
    cmd_direct = llm_cmd_direct or llm_cmd
    cmd_rlm = llm_cmd_rlm or llm_cmd

    # Generate context
    data = generate_needle_context(size=size, needle_type=needle_type, seed=seed)
    token_count = data["context_length"]

    # Write sandbox to temp dir
    tmp_dir = tempfile.mkdtemp(prefix="niah_bench_")
    try:
        write_sandbox(data, tmp_dir)
        question = data["question"]
        expected = data["answer"]
        results = []

        modes = ["direct", "rlm"] if mode == "both" else [mode]

        for m in modes:
            if m == "direct":
                cmd_used = cmd_direct
                actual, elapsed = _run_direct(question, tmp_dir, cmd_used)
            else:
                cmd_used = cmd_rlm
                actual, elapsed = _run_rlm(question, tmp_dir, cmd_used)

            sc = score_answer(actual, expected, needle_type)
            results.append(make_result(
                mode=m,
                needle_type=needle_type,
                size=size,
                seed=seed,
                expected=expected,
                actual=actual,
                score=sc,
                elapsed=elapsed,
                token_count=token_count,
                llm_cmd=cmd_used,
            ))

        return results
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]) -> None:
    """Print a human-readable summary table to stdout."""
    if not results:
        print("No results.")
        return

    # Group by mode
    modes = sorted(set(r["mode"] for r in results))
    print(f"\n{'='*72}")
    print(f"NIAH Benchmark Results — {len(results)} trial(s)")
    print(f"{'='*72}")

    for mode in modes:
        mode_results = [r for r in results if r["mode"] == mode]
        scores = [r["score"] for r in mode_results]
        times = [r["elapsed_seconds"] for r in mode_results]
        tokens = [r["token_count"] for r in mode_results]
        avg_score = sum(scores) / len(scores)
        avg_time = sum(times) / len(times)
        avg_tokens = sum(tokens) / len(tokens)

        print(f"\n  Mode: {mode.upper()}")
        print(f"  Trials:      {len(mode_results)}")
        print(f"  Avg Score:   {avg_score:.2%}")
        print(f"  Avg Time:    {avg_time:.1f}s")
        print(f"  Avg Tokens:  {avg_tokens:.0f}")

        # Per-trial detail
        print(f"  {'Seed':<6} {'Score':<8} {'Time':<8} {'Tokens':<8} {'Expected':<20} {'Actual (truncated)'}")
        print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*20} {'-'*30}")
        for r in mode_results:
            actual_short = str(r["actual"])[:40].replace("\n", " ")
            expected_short = str(r["expected"])[:20]
            print(
                f"  {r['seed']:<6} {r['score']:<8.2%} "
                f"{r['elapsed_seconds']:<8.1f} {r['token_count']:<8} "
                f"{expected_short:<20} {actual_short}"
            )

    print(f"\n{'='*72}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="NIAH Benchmark — generate, test (LLM vs RLM), evaluate"
    )
    parser.add_argument("--size", type=int, required=True,
                        help="Context size in tokens")
    parser.add_argument("--needle-type", type=str, required=True,
                        choices=["retrieval", "counting", "reasoning"],
                        dest="needle_type")
    parser.add_argument("--seed", type=int, default=None,
                        help="Single seed (use --seeds for multiple)")
    parser.add_argument("--seeds", type=str, default=None,
                        help="Comma-separated list of seeds (e.g. 1,2,3,4,5)")
    parser.add_argument("--mode", type=str, required=True,
                        choices=["direct", "rlm", "both"],
                        help="Test mode: direct (full context), rlm, or both")
    parser.add_argument("--llm-cmd", type=str, default=None, dest="llm_cmd",
                        help="Default LLM shell command for both modes")
    parser.add_argument("--llm-cmd-direct", type=str, default=None, dest="llm_cmd_direct",
                        help="LLM command for direct mode (overrides --llm-cmd)")
    parser.add_argument("--llm-cmd-rlm", type=str, default=None, dest="llm_cmd_rlm",
                        help="LLM command for RLM mode (overrides --llm-cmd)")
    parser.add_argument("--results", type=str, required=True,
                        help="Output JSON file for results")
    args = parser.parse_args()

    # Validate: at least one LLM command must be provided
    if not args.llm_cmd and not args.llm_cmd_direct and not args.llm_cmd_rlm:
        parser.error("At least one of --llm-cmd, --llm-cmd-direct, --llm-cmd-rlm is required")
    # Validate: mode-specific commands are available
    if args.mode in ("direct", "both") and not (args.llm_cmd or args.llm_cmd_direct):
        parser.error("Direct mode requires --llm-cmd or --llm-cmd-direct")
    if args.mode in ("rlm", "both") and not (args.llm_cmd or args.llm_cmd_rlm):
        parser.error("RLM mode requires --llm-cmd or --llm-cmd-rlm")

    # Resolve seeds
    if args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(",")]
    elif args.seed is not None:
        seeds = [args.seed]
    else:
        parser.error("Either --seed or --seeds is required")

    all_results = []

    for i, seed in enumerate(seeds):
        print(f"[{i+1}/{len(seeds)}] Running seed={seed}, "
              f"size={args.size}, type={args.needle_type}, mode={args.mode}...")

        trial_results = run_benchmark(
            size=args.size,
            needle_type=args.needle_type,
            seed=seed,
            mode=args.mode,
            llm_cmd=args.llm_cmd or "",
            llm_cmd_direct=args.llm_cmd_direct,
            llm_cmd_rlm=args.llm_cmd_rlm,
        )
        all_results.extend(trial_results)

    # Write results
    Path(args.results).write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Print summary
    print_summary(all_results)
    print(f"Results written to {args.results}")


if __name__ == "__main__":
    main()
