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

    # Compare direct vs RLM
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
        return f"[LLM error: {result.stderr.strip()[:200]}]", elapsed
    return result.stdout.strip(), elapsed


def _run_rlm(question: str, sandbox_dir: str, llm_cmd: str) -> tuple[str, float]:
    """Run the question through the RLM skill.

    Returns (response, elapsed_seconds).
    """
    rlm_script = os.path.join(
        os.path.dirname(__file__), "..", "..", "skills", "rlm", "rlm.py"
    )
    rlm_script = os.path.normpath(rlm_script)

    sb = os.path.join(sandbox_dir, "sandbox")

    cmd = [
        sys.executable, rlm_script,
        "--query", question,
        "--input", sb,
        "--llm-cmd", llm_cmd,
    ]

    start = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        return f"[RLM error: {result.stderr.strip()[:200]}]", elapsed
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
) -> list[dict]:
    """Run one or two benchmark trials (direct and/or rlm).

    Returns a list of result dicts.
    """
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
                actual, elapsed = _run_direct(question, tmp_dir, llm_cmd)
            else:
                actual, elapsed = _run_rlm(question, tmp_dir, llm_cmd)

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
    parser.add_argument("--llm-cmd", type=str, required=True, dest="llm_cmd",
                        help="Shell command: reads prompt from stdin, writes answer to stdout")
    parser.add_argument("--results", type=str, required=True,
                        help="Output JSON file for results")
    args = parser.parse_args()

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
            llm_cmd=args.llm_cmd,
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
