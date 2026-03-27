import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

from unittest.mock import patch
from rlm import rlm


def test_direct_answer(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("Hello world\n")
    manifest = {str(f): (1, 1)}
    with patch("rlm.call_llm", return_value="<answer>Hello world</answer>"):
        result = rlm("What is written?", manifest, "unused", max_depth=4, max_turns=10)
    assert result == "Hello world"


def test_peek_then_answer(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("secret: 42\n")
    manifest = {str(f): (1, 1)}
    responses = iter([
        f'<peek file="{f}" lines="1-1"/>',
        "<answer>The secret is 42</answer>",
    ])
    with patch("rlm.call_llm", side_effect=responses):
        result = rlm("What is the secret?", manifest, "unused", max_depth=4, max_turns=10)
    assert result == "The secret is 42"


def test_recurse_then_answer(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def login(): pass\n" * 5)
    manifest = {str(f): (1, 5)}
    # call sequence: outer turn1=recurse, inner turn1=answer, outer turn2=answer
    responses = iter([
        f'<recurse query="What does login() do?" file="{f}" lines="1-5"/>',
        "<answer>login() is a stub</answer>",
        "<answer>The login function is a stub</answer>",
    ])
    with patch("rlm.call_llm", side_effect=responses):
        result = rlm("Describe the code", manifest, "unused", max_depth=4, max_turns=10)
    assert "stub" in result


def test_max_depth_respected(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("data\n")
    manifest = {str(f): (1, 1)}
    with patch("rlm.call_llm", return_value=f'<recurse query="sub" file="{f}" lines="1-1"/>'):
        result = rlm("query", manifest, "unused", max_depth=1, max_turns=10)
    # Either the depth limit or the global call budget terminates the run.
    assert "Max recursion depth" in result or "budget" in result.lower()


def test_max_turns_returns_partial_context(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("line1\n")
    manifest = {str(f): (1, 1)}
    with patch("rlm.call_llm", return_value=f'<peek file="{f}" lines="1-1"/>'):
        result = rlm("query", manifest, "unused", max_depth=4, max_turns=2)
    assert result != ""
    assert "line1" in result


def test_graceful_fallback_no_tag(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("hello\n")
    manifest = {str(f): (1, 1)}
    with patch("rlm.call_llm", return_value="The answer is 42, no tags."):
        result = rlm("query", manifest, "unused", max_depth=4, max_turns=10)
    assert result == "The answer is 42, no tags."


def test_empty_manifest_path_returns_answer(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("content\n")
    manifest = {str(f): (1, 1)}
    with patch("rlm.call_llm", return_value="<answer>ok</answer>"):
        result = rlm("q", manifest, "unused", max_depth=4, max_turns=10)
    assert result == "ok"


def test_global_call_budget_prevents_explosion(tmp_path):
    """A misbehaving LLM that always recurses must not exceed the global call budget."""
    f = tmp_path / "file.txt"
    f.write_text("data\n")
    manifest = {str(f): (1, 1)}
    call_count = [0]
    def counting_llm(prompt, cmd):
        call_count[0] += 1
        return f'<recurse query="sub" file="{f}" lines="1-1"/>'
    with patch("rlm.call_llm", side_effect=counting_llm):
        result = rlm("query", manifest, "unused", max_depth=4, max_turns=10)
    assert "budget" in result.lower() or "depth" in result.lower()
    assert call_count[0] <= 200  # well within sane limits
