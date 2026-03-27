import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

from rlm import parse_tags, PeekTag, RecurseTag, AnswerTag


def test_parse_answer():
    result = parse_tags("<answer>The answer is 42.</answer>")
    assert isinstance(result, AnswerTag)
    assert result.content == "The answer is 42."


def test_parse_answer_strips_whitespace():
    result = parse_tags("<answer>\n  trimmed  \n</answer>")
    assert result.content == "trimmed"


def test_parse_answer_multiline():
    result = parse_tags("<answer>\nline1\nline2\n</answer>")
    assert result.content == "line1\nline2"


def test_parse_peek():
    result = parse_tags('<peek file="src/auth.py" lines="1-50"/>')
    assert isinstance(result, PeekTag)
    assert result.file == "src/auth.py"
    assert result.start == 1
    assert result.end == 50


def test_parse_peek_any_attribute_order():
    result = parse_tags('<peek lines="10-20" file="src/main.py"/>')
    assert isinstance(result, PeekTag)
    assert result.file == "src/main.py"
    assert result.start == 10
    assert result.end == 20


def test_parse_recurse():
    result = parse_tags('<recurse query="What does login() do?" file="src/auth.py" lines="51-200"/>')
    assert isinstance(result, RecurseTag)
    assert result.query == "What does login() do?"
    assert result.file == "src/auth.py"
    assert result.start == 51
    assert result.end == 200


def test_answer_takes_priority_over_peek():
    result = parse_tags('<peek file="x.py" lines="1-5"/> <answer>done</answer>')
    assert isinstance(result, AnswerTag)
    assert result.content == "done"


def test_fallback_on_no_tag():
    result = parse_tags("The answer is 42.")
    assert isinstance(result, AnswerTag)
    assert result.content == "The answer is 42."


def test_fallback_on_malformed_peek_no_attrs():
    result = parse_tags("<peek/>")
    assert isinstance(result, AnswerTag)


def test_fallback_on_peek_missing_lines():
    result = parse_tags('<peek file="x.py"/>')
    assert isinstance(result, AnswerTag)


def test_fallback_on_inverted_range_peek():
    result = parse_tags('<peek file="x.py" lines="50-10"/>')
    assert isinstance(result, AnswerTag)


def test_fallback_on_inverted_range_recurse():
    result = parse_tags('<recurse query="q" file="x.py" lines="50-10"/>')
    assert isinstance(result, AnswerTag)


def test_fallback_on_recurse_missing_attrs():
    result = parse_tags('<recurse file="x.py" lines="1-5"/>')  # missing query
    assert isinstance(result, AnswerTag)


def test_answer_takes_priority_over_recurse():
    result = parse_tags('<recurse query="q" file="x.py" lines="1-5"/> <answer>done</answer>')
    assert isinstance(result, AnswerTag)
    assert result.content == "done"


def test_peek_takes_priority_over_recurse():
    result = parse_tags('<recurse query="q" file="x.py" lines="1-5"/> <peek file="x.py" lines="1-5"/>')
    assert isinstance(result, PeekTag)
