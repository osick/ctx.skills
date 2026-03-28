"""Tests for the NIAH benchmark runner."""
import json
import os
import subprocess
import sys
import textwrap
import pytest
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Tests for _run_direct: LLM runs in sandbox directory, not via piped context
# ---------------------------------------------------------------------------

class TestRunDirectSandbox:
    """Verify that _run_direct creates context.txt and runs LLM in the sandbox dir."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    @pytest.fixture
    def sandbox(self, tmp_path):
        """Create a minimal sandbox with chunk files."""
        from generate_context import generate_needle_context, write_sandbox
        data = generate_needle_context(size=500, needle_type="retrieval", seed=42)
        write_sandbox(data, str(tmp_path))
        return tmp_path, data

    def test_context_txt_created(self, sandbox):
        """_run_direct should create a context.txt in the sandbox dir."""
        tmp_path, data = sandbox
        # Use a dummy LLM that just prints its cwd
        llm_cmd = "pwd"
        self.mod._run_direct(data["question"], str(tmp_path), llm_cmd)
        context_file = tmp_path / "sandbox" / "context.txt"
        assert context_file.exists(), "context.txt should be created in sandbox dir"

    def test_context_txt_contains_all_chunks(self, sandbox):
        """context.txt should contain the concatenated content of all chunk files."""
        tmp_path, data = sandbox
        llm_cmd = "echo dummy"
        self.mod._run_direct(data["question"], str(tmp_path), llm_cmd)
        context_file = tmp_path / "sandbox" / "context.txt"
        combined = context_file.read_text(encoding="utf-8")
        # Verify it contains content from all chunk files
        sb_dir = tmp_path / "sandbox"
        for f in sorted(sb_dir.glob("chunk_*.txt")):
            chunk_content = f.read_text(encoding="utf-8")
            assert chunk_content in combined, f"context.txt should contain {f.name}"

    def test_llm_runs_in_sandbox_dir(self, sandbox):
        """The LLM command should execute with cwd set to the sandbox directory."""
        tmp_path, data = sandbox
        # LLM command prints its working directory
        llm_cmd = "pwd"
        response, elapsed = self.mod._run_direct(data["question"], str(tmp_path), llm_cmd)
        expected_cwd = str(tmp_path / "sandbox")
        assert response.strip() == expected_cwd, (
            f"LLM should run in sandbox dir {expected_cwd}, got {response.strip()}"
        )

    def test_prompt_does_not_contain_full_context(self, sandbox):
        """The prompt sent to LLM stdin should NOT contain the full context text."""
        tmp_path, data = sandbox
        # LLM command dumps stdin to a file so we can inspect it
        dump_file = tmp_path / "stdin_dump.txt"
        llm_cmd = f"cat > {dump_file}"
        self.mod._run_direct(data["question"], str(tmp_path), llm_cmd)
        stdin_content = dump_file.read_text(encoding="utf-8")
        # The prompt should contain the question
        assert data["question"] in stdin_content, "Prompt should contain the question"
        # The prompt should NOT contain the full concatenated context
        sb_dir = tmp_path / "sandbox"
        full_context = "\n".join(
            f.read_text(encoding="utf-8") for f in sorted(sb_dir.glob("chunk_*.txt"))
        )
        assert full_context not in stdin_content, (
            "Prompt should NOT contain the full context — LLM should read files itself"
        )

    def test_prompt_mentions_files(self, sandbox):
        """The prompt should instruct the LLM to look at files in the directory."""
        tmp_path, data = sandbox
        dump_file = tmp_path / "stdin_dump.txt"
        llm_cmd = f"cat > {dump_file}"
        self.mod._run_direct(data["question"], str(tmp_path), llm_cmd)
        stdin_content = dump_file.read_text(encoding="utf-8").lower()
        # Should mention files or directory
        assert any(word in stdin_content for word in ["file", "context.txt", "read"]), (
            "Prompt should instruct LLM to read files in the directory"
        )
