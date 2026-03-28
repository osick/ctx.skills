"""Tests for the NIAH benchmark runner."""
import json
import os
import subprocess
import sys
import textwrap
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "benchmark.py")
GEN_SCRIPT = os.path.join(os.path.dirname(__file__), "generate_context.py")


def _run(args: list[str], check=True, timeout=30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, check=check, timeout=timeout,
    )


def _make_echo_cmd(response: str) -> str:
    """Build a shell command that ignores stdin and echoes a fixed response."""
    return f"echo '{response}'"


# ---------------------------------------------------------------------------
# Unit tests for evaluation logic (import the module directly)
# ---------------------------------------------------------------------------

class TestEvaluation:
    """Test the scoring/evaluation functions."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_exact_match_correct(self):
        score = self.mod.score_answer("Berlin", "Berlin", "retrieval")
        assert score == 1.0

    def test_exact_match_case_insensitive(self):
        score = self.mod.score_answer("berlin", "Berlin", "retrieval")
        assert score == 1.0

    def test_exact_match_wrong(self):
        score = self.mod.score_answer("Tokyo", "Berlin", "retrieval")
        assert score == 0.0

    def test_partial_match_substring(self):
        score = self.mod.score_answer(
            "The answer is Berlin I think", "Berlin", "retrieval"
        )
        assert score > 0.0

    def test_counting_all_correct(self):
        score = self.mod.score_answer("42, 7, 91", [42, 7, 91], "counting")
        assert score == 1.0

    def test_counting_partial(self):
        score = self.mod.score_answer("42, 7", [42, 7, 91], "counting")
        assert 0.0 < score < 1.0

    def test_counting_none_found(self):
        score = self.mod.score_answer("no numbers here", [42, 7, 91], "counting")
        assert score == 0.0

    def test_reasoning_correct(self):
        score = self.mod.score_answer("Xiaoming", "Xiaoming", "reasoning")
        assert score == 1.0

    def test_reasoning_in_sentence(self):
        score = self.mod.score_answer(
            "Based on the clues, Xiaoming is the tallest.", "Xiaoming", "reasoning"
        )
        assert score > 0.0


# ---------------------------------------------------------------------------
# Result format
# ---------------------------------------------------------------------------

class TestResultFormat:
    """Test that the benchmark produces well-structured result JSON."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_result_fields(self):
        result = self.mod.make_result(
            mode="direct",
            needle_type="retrieval",
            size=1000,
            seed=1,
            expected="Berlin",
            actual="Berlin",
            score=1.0,
            elapsed=2.5,
            token_count=1000,
        )
        assert result["mode"] == "direct"
        assert result["needle_type"] == "retrieval"
        assert result["size"] == 1000
        assert result["score"] == 1.0
        assert result["elapsed_seconds"] == 2.5
        assert result["token_count"] == 1000
        assert result["expected"] == "Berlin"
        assert result["actual"] == "Berlin"


# ---------------------------------------------------------------------------
# CLI integration (using a mock llm-cmd that echoes a fixed answer)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_direct_mode_produces_results(self, tmp_path):
        """Run a single direct-mode benchmark with a mock LLM."""
        results_file = tmp_path / "results.json"
        # The mock LLM always answers "Berlin"
        r = _run([
            "--size", "500",
            "--needle-type", "retrieval",
            "--seed", "1",
            "--mode", "direct",
            "--llm-cmd", _make_echo_cmd("Berlin"),
            "--results", str(results_file),
        ])
        assert results_file.exists()
        data = json.loads(results_file.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert "score" in data[0]
        assert "elapsed_seconds" in data[0]
        assert "token_count" in data[0]
        assert data[0]["mode"] == "direct"

    def test_rlm_mode_produces_results(self, tmp_path):
        """Run a single RLM-mode benchmark with a mock LLM."""
        results_file = tmp_path / "results.json"
        # The mock LLM wraps its answer in <answer> tags (RLM protocol)
        r = _run([
            "--size", "500",
            "--needle-type", "retrieval",
            "--seed", "1",
            "--mode", "rlm",
            "--llm-cmd", _make_echo_cmd("<answer>Berlin</answer>"),
            "--results", str(results_file),
        ])
        assert results_file.exists()
        data = json.loads(results_file.read_text())
        assert len(data) == 1
        assert data[0]["mode"] == "rlm"

    def test_both_modes(self, tmp_path):
        """--mode both should produce two results."""
        results_file = tmp_path / "results.json"
        r = _run([
            "--size", "500",
            "--needle-type", "retrieval",
            "--seed", "1",
            "--mode", "both",
            "--llm-cmd", _make_echo_cmd("<answer>Berlin</answer>"),
            "--results", str(results_file),
        ])
        data = json.loads(results_file.read_text())
        assert len(data) == 2
        modes = {d["mode"] for d in data}
        assert modes == {"direct", "rlm"}

    def test_multiple_seeds(self, tmp_path):
        """--seeds 1,2,3 should produce one result per seed (per mode)."""
        results_file = tmp_path / "results.json"
        r = _run([
            "--size", "500",
            "--needle-type", "retrieval",
            "--seeds", "1,2,3",
            "--mode", "direct",
            "--llm-cmd", _make_echo_cmd("Berlin"),
            "--results", str(results_file),
        ])
        data = json.loads(results_file.read_text())
        assert len(data) == 3

    def test_stdout_summary(self, tmp_path):
        """Benchmark should print a summary to stdout."""
        r = _run([
            "--size", "500",
            "--needle-type", "retrieval",
            "--seed", "1",
            "--mode", "direct",
            "--llm-cmd", _make_echo_cmd("Berlin"),
            "--results", str(tmp_path / "r.json"),
        ])
        assert "score" in r.stdout.lower() or "result" in r.stdout.lower()

    def test_missing_llm_cmd(self):
        r = _run(["--size", "500", "--needle-type", "retrieval", "--seed", "1",
                   "--mode", "direct"], check=False)
        assert r.returncode != 0
