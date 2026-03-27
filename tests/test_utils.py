import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

from rlm import peek_lines, call_llm
from unittest.mock import patch
import subprocess


def test_peek_lines_correct_range(tmp_path):
    f = tmp_path / "text.txt"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    result = peek_lines(str(f), 2, 4)
    assert "line2" in result
    assert "line3" in result
    assert "line4" in result
    assert "line1" not in result
    assert "line5" not in result


def test_peek_lines_includes_line_numbers(tmp_path):
    f = tmp_path / "text.txt"
    f.write_text("hello\nworld\n")
    result = peek_lines(str(f), 1, 2)
    assert "1:" in result
    assert "2:" in result


def test_peek_lines_missing_file():
    result = peek_lines("/nonexistent/path.txt", 1, 10)
    assert "[Error reading" in result


def test_call_llm_returns_stdout():
    result = call_llm("hello", "echo world")
    assert result == "world"


def test_call_llm_passes_prompt_via_stdin():
    result = call_llm("secret", "cat")
    assert result == "secret"


def test_call_llm_raises_on_nonzero_exit():
    import pytest
    with pytest.raises(RuntimeError, match="LLM command failed"):
        call_llm("prompt", "exit 1")
