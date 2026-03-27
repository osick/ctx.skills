import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

from prompt import build_prompt, SYSTEM_PROMPT


def test_build_prompt_contains_query():
    manifest = {"src/auth.py": (1, 100)}
    result = build_prompt("Find login logic", manifest)
    assert "Find login logic" in result


def test_build_prompt_contains_manifest_entry():
    manifest = {"src/auth.py": (1, 100)}
    result = build_prompt("query", manifest)
    assert "src/auth.py" in result
    assert "1-100" in result


def test_build_prompt_contains_system_prompt():
    manifest = {"f.txt": (1, 5)}
    result = build_prompt("q", manifest)
    assert SYSTEM_PROMPT in result


def test_build_prompt_no_context_by_default():
    manifest = {"f.txt": (1, 5)}
    result = build_prompt("q", manifest)
    assert "Context gathered so far" not in result


def test_build_prompt_includes_context_items():
    manifest = {"f.txt": (1, 5)}
    result = build_prompt("q", manifest, context_items=["[peek f.txt]\nhello"])
    assert "Context gathered so far" in result
    assert "[peek f.txt]" in result


def test_build_prompt_multiple_manifest_entries():
    manifest = {
        "src/auth.py":   (1, 312),
        "src/models.py": (1, 89),
    }
    result = build_prompt("q", manifest)
    assert "src/auth.py" in result
    assert "src/models.py" in result
    assert "1-312" in result
    assert "1-89" in result


def test_build_prompt_empty_context_items_not_included():
    """Empty list should behave same as None — no context section."""
    manifest = {"f.txt": (1, 5)}
    result = build_prompt("q", manifest, context_items=[])
    assert "Context gathered so far" not in result


def test_build_prompt_multiple_context_items_separated():
    """Multiple context items should be separated by ---."""
    manifest = {"f.txt": (1, 5)}
    result = build_prompt("q", manifest, context_items=["item1", "item2"])
    assert "item1" in result
    assert "item2" in result
    assert "---" in result
