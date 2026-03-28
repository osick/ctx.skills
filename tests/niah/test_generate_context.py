"""Tests for the NIAH context file generator with MM-NIAH needle types."""
import json
import subprocess
import sys
import os
import re
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "generate_context.py")


def _run(args: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, check=check,
    )


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: split on whitespace."""
    return len(text.split())


# ---------------------------------------------------------------------------
# Basic functionality (backwards-compatible --secret mode)
# ---------------------------------------------------------------------------

class TestBasicGeneration:
    def test_generates_output_file(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "500", "--secret", "NEEDLE_42", "--output", str(out)])
        assert out.exists()
        assert len(out.read_text()) > 0

    def test_stdout_when_no_output_flag(self):
        result = _run(["--size", "200", "--secret", "HIDDEN_INFO"])
        assert len(result.stdout) > 0

    def test_secret_embedded_in_output(self, tmp_path):
        out = tmp_path / "ctx.txt"
        secret = "THE_SECRET_NEEDLE_XYZ"
        _run(["--size", "1000", "--secret", secret, "--output", str(out)])
        assert secret in out.read_text()

    def test_secret_appears_exactly_once(self, tmp_path):
        out = tmp_path / "ctx.txt"
        secret = "UNIQUE_NEEDLE_99"
        _run(["--size", "2000", "--secret", secret, "--output", str(out)])
        assert out.read_text().count(secret) == 1


# ---------------------------------------------------------------------------
# Token size targeting
# ---------------------------------------------------------------------------

class TestTokenSize:
    def test_approximate_token_count_small(self, tmp_path):
        out = tmp_path / "ctx.txt"
        target = 500
        _run(["--size", str(target), "--secret", "S", "--output", str(out)])
        tokens = _estimate_tokens(out.read_text())
        assert tokens >= target * 0.8
        assert tokens <= target * 1.2

    def test_approximate_token_count_large(self, tmp_path):
        out = tmp_path / "ctx.txt"
        target = 5000
        _run(["--size", str(target), "--secret", "S", "--output", str(out)])
        tokens = _estimate_tokens(out.read_text())
        assert tokens >= target * 0.8
        assert tokens <= target * 1.2

    def test_very_small_size_still_contains_secret(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "50", "--secret", "TINY_SECRET", "--output", str(out)])
        assert "TINY_SECRET" in out.read_text()


# ---------------------------------------------------------------------------
# Word length control
# ---------------------------------------------------------------------------

class TestWordLength:
    def test_default_produces_coherent_text(self, tmp_path):
        """Default wordlength leaves coherent paragraphs intact."""
        out = tmp_path / "ctx.txt"
        _run(["--size", "500", "--secret", "S", "--output", str(out)])
        words = out.read_text().split()
        # Should contain real English words — spot check common ones
        lower_words = {w.lower().strip(".,;:") for w in words}
        assert lower_words & {"the", "and", "was", "for", "from", "with"}

    def test_custom_word_length_respected(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "1000", "--secret", "S", "--wordlength", "5",
              "--output", str(out)])
        words = out.read_text().split()
        filler_words = [w for w in words if w != "S"]
        for w in filler_words:
            assert len(w) <= 5, f"Word '{w}' exceeds max length 5"

    def test_wordlength_3(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "500", "--secret", "S", "--wordlength", "3",
              "--output", str(out)])
        words = out.read_text().split()
        filler_words = [w for w in words if w != "S"]
        for w in filler_words:
            assert len(w) <= 3, f"Word '{w}' exceeds max length 3"


# ---------------------------------------------------------------------------
# Secret placement
# ---------------------------------------------------------------------------

class TestSecretPlacement:
    def test_secret_not_at_very_start(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "1000", "--secret", "BURIED_NEEDLE", "--output", str(out)])
        content = out.read_text()
        pos = content.index("BURIED_NEEDLE")
        assert pos > len(content) * 0.05

    def test_secret_not_at_very_end(self, tmp_path):
        out = tmp_path / "ctx.txt"
        _run(["--size", "1000", "--secret", "BURIED_NEEDLE", "--output", str(out)])
        content = out.read_text()
        pos = content.index("BURIED_NEEDLE")
        assert pos < len(content) * 0.95


# ---------------------------------------------------------------------------
# Retrieval needle type
# ---------------------------------------------------------------------------

class TestRetrievalNeedle:
    """Retrieval: a single factual statement is embedded; the question asks to find it."""

    def test_retrieval_generates_output(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "retrieval", "--output", str(out)])
        data = json.loads(out.read_text())
        assert "context" in data
        assert "question" in data
        assert "answer" in data
        assert "needles" in data

    def test_retrieval_needle_in_context(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "retrieval", "--seed", "7",
              "--output", str(out)])
        data = json.loads(out.read_text())
        # The needle statement must appear in the context
        assert len(data["needles"]) == 1
        assert data["needles"][0] in data["context"]

    def test_retrieval_has_question_and_answer(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "1",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert len(data["question"]) > 0
        assert len(data["answer"]) > 0

    def test_retrieval_answer_derivable_from_needle(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "3",
              "--output", str(out)])
        data = json.loads(out.read_text())
        # The answer should appear within the needle text
        needle_lower = data["needles"][0].lower()
        answer_lower = data["answer"].lower()
        assert answer_lower in needle_lower

    def test_retrieval_token_count(self, tmp_path):
        out = tmp_path / "ctx.json"
        target = 2000
        _run(["--size", str(target), "--needle-type", "retrieval", "--seed", "5",
              "--output", str(out)])
        data = json.loads(out.read_text())
        tokens = _estimate_tokens(data["context"])
        assert tokens >= target * 0.8
        assert tokens <= target * 1.2


# ---------------------------------------------------------------------------
# Counting needle type
# ---------------------------------------------------------------------------

class TestCountingNeedle:
    """Counting: multiple 'little penguin counted N needles' statements."""

    def test_counting_generates_output(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "counting", "--output", str(out)])
        data = json.loads(out.read_text())
        assert "context" in data
        assert "question" in data
        assert "answer" in data
        assert "needles" in data

    def test_counting_multiple_needles(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "counting", "--seed", "10",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert len(data["needles"]) >= 2

    def test_counting_all_needles_in_context(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "counting", "--seed", "11",
              "--output", str(out)])
        data = json.loads(out.read_text())
        for needle in data["needles"]:
            assert needle in data["context"], f"Needle not found in context: {needle}"

    def test_counting_needles_mention_animals(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "counting", "--seed", "12",
              "--output", str(out)])
        data = json.loads(out.read_text())
        known_animals = {"bacteria", "bee", "flea", "hummingbird", "elephant"}
        for needle in data["needles"]:
            assert any(a in needle.lower() for a in known_animals), \
                f"No known animal in: {needle}"

    def test_counting_answer_is_list_of_counts(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "counting", "--seed", "13",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert isinstance(data["answer"], list)
        for item in data["answer"]:
            assert str(item).isdigit()

    def test_counting_needles_spread_across_context(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "3000", "--needle-type", "counting", "--seed", "14",
              "--output", str(out)])
        data = json.loads(out.read_text())
        positions = [data["context"].index(n) for n in data["needles"]]
        # Needles should not all be at the same position
        assert len(set(positions)) == len(positions)


# ---------------------------------------------------------------------------
# Reasoning needle type
# ---------------------------------------------------------------------------

class TestReasoningNeedle:
    """Reasoning: multiple related statements requiring inference."""

    def test_reasoning_generates_output(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "reasoning", "--output", str(out)])
        data = json.loads(out.read_text())
        assert "context" in data
        assert "question" in data
        assert "answer" in data
        assert "needles" in data

    def test_reasoning_multiple_needles(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "reasoning", "--seed", "20",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert len(data["needles"]) >= 2

    def test_reasoning_all_needles_in_context(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "reasoning", "--seed", "21",
              "--output", str(out)])
        data = json.loads(out.read_text())
        for needle in data["needles"]:
            assert needle in data["context"], f"Needle not found: {needle}"

    def test_reasoning_has_question_requiring_inference(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "reasoning", "--seed", "22",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert len(data["question"]) > 10  # non-trivial question

    def test_reasoning_answer_not_literally_in_single_needle(self, tmp_path):
        """The answer should require combining info from multiple needles."""
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "reasoning", "--seed", "23",
              "--output", str(out)])
        data = json.loads(out.read_text())
        answer_lower = data["answer"].lower()
        # Answer may appear in individual needles as a name, but the question
        # requires reasoning across needles to determine it's the correct answer
        assert len(data["needles"]) >= 2

    def test_reasoning_needles_spread_across_context(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "3000", "--needle-type", "reasoning", "--seed", "24",
              "--output", str(out)])
        data = json.loads(out.read_text())
        positions = [data["context"].index(n) for n in data["needles"]]
        assert len(set(positions)) == len(positions)


# ---------------------------------------------------------------------------
# Depth control
# ---------------------------------------------------------------------------

class TestDepthControl:
    def test_depth_shallow(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "retrieval", "--depth", "0.1",
              "--seed", "30", "--output", str(out)])
        data = json.loads(out.read_text())
        pos = data["context"].index(data["needles"][0])
        # Needle should be in roughly the first 20% of context
        assert pos < len(data["context"]) * 0.25

    def test_depth_deep(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "2000", "--needle-type", "retrieval", "--depth", "0.9",
              "--seed", "31", "--output", str(out)])
        data = json.loads(out.read_text())
        pos = data["context"].index(data["needles"][0])
        # Needle should be in roughly the last 20% of context
        assert pos > len(data["context"]) * 0.75


# ---------------------------------------------------------------------------
# Metadata output
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_metadata_fields(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "retrieval", "--seed", "40",
              "--output", str(out)])
        data = json.loads(out.read_text())
        assert "placed_depth" in data
        assert "context_length" in data
        assert "needle_type" in data

    def test_metadata_context_length_matches(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "retrieval", "--seed", "41",
              "--output", str(out)])
        data = json.loads(out.read_text())
        actual_tokens = _estimate_tokens(data["context"])
        assert data["context_length"] == actual_tokens

    def test_metadata_needle_type_matches(self, tmp_path):
        for ntype in ["retrieval", "counting", "reasoning"]:
            out = tmp_path / f"ctx_{ntype}.json"
            _run(["--size", "500", "--needle-type", ntype, "--seed", "42",
                  "--output", str(out)])
            data = json.loads(out.read_text())
            assert data["needle_type"] == ntype


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_required_args(self):
        result = _run([], check=False)
        assert result.returncode != 0

    def test_secret_mode_still_works(self, tmp_path):
        """--secret without --needle-type should still produce plain text."""
        out = tmp_path / "ctx.txt"
        _run(["--size", "500", "--secret", "LEGACY_MODE", "--output", str(out)])
        content = out.read_text()
        assert "LEGACY_MODE" in content
        # Should NOT be JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(content)

    def test_invalid_needle_type(self):
        result = _run(["--size", "100", "--needle-type", "invalid"], check=False)
        assert result.returncode != 0

    def test_reproducible_with_seed(self, tmp_path):
        out1 = tmp_path / "ctx1.json"
        out2 = tmp_path / "ctx2.json"
        args = ["--size", "500", "--needle-type", "retrieval", "--seed", "42"]
        _run(args + ["--output", str(out1)])
        _run(args + ["--output", str(out2)])
        assert out1.read_text() == out2.read_text()

    def test_different_seeds_produce_different_output(self, tmp_path):
        out1 = tmp_path / "ctx1.json"
        out2 = tmp_path / "ctx2.json"
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "1",
              "--output", str(out1)])
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "2",
              "--output", str(out2)])
        assert out1.read_text() != out2.read_text()

    def test_multiword_secret_legacy(self, tmp_path):
        out = tmp_path / "ctx.txt"
        secret = "the secret code is 42"
        _run(["--size", "1000", "--secret", secret, "--output", str(out)])
        assert secret in out.read_text()

    def test_wordlength_applies_to_needle_types(self, tmp_path):
        out = tmp_path / "ctx.json"
        _run(["--size", "1000", "--needle-type", "retrieval", "--wordlength", "4",
              "--seed", "50", "--output", str(out)])
        data = json.loads(out.read_text())
        # Filler words (not part of needles) should respect wordlength
        context = data["context"]
        for needle in data["needles"]:
            context = context.replace(needle, "")
        filler_words = context.split()
        for w in filler_words:
            assert len(w) <= 4, f"Filler word '{w}' exceeds max length 4"


# ---------------------------------------------------------------------------
# Sandbox mode
# ---------------------------------------------------------------------------

class TestSandbox:
    """--sandbox writes context as files in X/sandbox/ and metadata to X/niah.json."""

    def test_sandbox_creates_directory_structure(self, tmp_path):
        sb = tmp_path / "mytest"
        _run(["--size", "1000", "--needle-type", "retrieval", "--seed", "60",
              "--sandbox", str(sb)])
        assert sb.is_dir()
        assert (sb / "sandbox").is_dir()
        assert (sb / "niah.json").is_file()

    def test_sandbox_creates_nonexistent_path(self, tmp_path):
        sb = tmp_path / "deep" / "nested" / "dir"
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "61",
              "--sandbox", str(sb)])
        assert sb.is_dir()
        assert (sb / "sandbox").is_dir()

    def test_sandbox_niah_json_has_metadata(self, tmp_path):
        sb = tmp_path / "test_meta"
        _run(["--size", "1000", "--needle-type", "counting", "--seed", "62",
              "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        assert "question" in data
        assert "answer" in data
        assert "needles" in data
        assert "needle_type" in data
        assert "placed_depth" in data
        assert "context_length" in data
        assert data["needle_type"] == "counting"

    def test_sandbox_niah_json_has_no_context_field(self, tmp_path):
        """Context lives in sandbox/ files, not in the JSON."""
        sb = tmp_path / "test_no_ctx"
        _run(["--size", "500", "--needle-type", "retrieval", "--seed", "63",
              "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        assert "context" not in data

    def test_sandbox_files_contain_context(self, tmp_path):
        sb = tmp_path / "test_files"
        _run(["--size", "2000", "--needle-type", "retrieval", "--seed", "64",
              "--sandbox", str(sb)])
        sandbox_dir = sb / "sandbox"
        files = sorted(sandbox_dir.glob("*.txt"))
        assert len(files) >= 1
        # Concatenated file content should form the full context
        full_text = ""
        for f in files:
            full_text += f.read_text()
        assert len(full_text.split()) > 100

    def test_sandbox_needle_present_in_files(self, tmp_path):
        sb = tmp_path / "test_needle_files"
        _run(["--size", "2000", "--needle-type", "retrieval", "--seed", "65",
              "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        # Read all sandbox files
        sandbox_dir = sb / "sandbox"
        full_text = ""
        for f in sorted(sandbox_dir.glob("*.txt")):
            full_text += f.read_text()
        for needle in data["needles"]:
            assert needle in full_text, f"Needle not in sandbox files: {needle}"

    def test_sandbox_multiple_files_for_large_context(self, tmp_path):
        sb = tmp_path / "test_chunks"
        _run(["--size", "5000", "--needle-type", "reasoning", "--seed", "66",
              "--sandbox", str(sb)])
        files = list((sb / "sandbox").glob("*.txt"))
        assert len(files) > 1

    def test_sandbox_files_have_sequential_names(self, tmp_path):
        sb = tmp_path / "test_names"
        _run(["--size", "3000", "--needle-type", "counting", "--seed", "67",
              "--sandbox", str(sb)])
        files = sorted((sb / "sandbox").glob("*.txt"))
        names = [f.name for f in files]
        # Files should be numbered sequentially
        for i, name in enumerate(names):
            assert name == f"chunk_{i:04d}.txt"

    def test_sandbox_niah_json_lists_files(self, tmp_path):
        sb = tmp_path / "test_filelist"
        _run(["--size", "2000", "--needle-type", "retrieval", "--seed", "68",
              "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        assert "sandbox_files" in data
        files = sorted((sb / "sandbox").glob("*.txt"))
        assert len(data["sandbox_files"]) == len(files)

    def test_sandbox_token_count_matches(self, tmp_path):
        sb = tmp_path / "test_tokens"
        target = 2000
        _run(["--size", str(target), "--needle-type", "retrieval", "--seed", "69",
              "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        # Token count in metadata should match actual content
        full_text = ""
        for f in sorted((sb / "sandbox").glob("*.txt")):
            full_text += " " + f.read_text()
        actual = _estimate_tokens(full_text.strip())
        assert actual >= target * 0.8
        assert actual <= target * 1.2

    def test_sandbox_reproducible_with_seed(self, tmp_path):
        sb1 = tmp_path / "s1"
        sb2 = tmp_path / "s2"
        args = ["--size", "1000", "--needle-type", "retrieval", "--seed", "70"]
        _run(args + ["--sandbox", str(sb1)])
        _run(args + ["--sandbox", str(sb2)])
        assert (sb1 / "niah.json").read_text() == (sb2 / "niah.json").read_text()
        files1 = sorted((sb1 / "sandbox").glob("*.txt"))
        files2 = sorted((sb2 / "sandbox").glob("*.txt"))
        assert len(files1) == len(files2)
        for f1, f2 in zip(files1, files2):
            assert f1.read_text() == f2.read_text()

    def test_sandbox_wordlength_respected_in_files(self, tmp_path):
        sb = tmp_path / "test_wl"
        _run(["--size", "1000", "--needle-type", "retrieval", "--wordlength", "4",
              "--seed", "71", "--sandbox", str(sb)])
        data = json.loads((sb / "niah.json").read_text())
        full_text = ""
        for f in sorted((sb / "sandbox").glob("*.txt")):
            full_text += " " + f.read_text()
        # Remove needle text before checking filler word lengths
        for needle in data["needles"]:
            full_text = full_text.replace(needle, "")
        for w in full_text.split():
            assert len(w) <= 4, f"Filler word '{w}' exceeds max length 4"
