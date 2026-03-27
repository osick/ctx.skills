import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

from rlm import build_manifest, _matches


# --- _matches ---

def test_matches_no_patterns():
    assert _matches("any/file.py", None) is True
    assert _matches("any/file.py", []) is True


def test_matches_glob():
    assert _matches("auth.py", ["*.py"]) is True
    assert _matches("auth.js", ["*.py"]) is False


def test_matches_multiple_patterns():
    assert _matches("test_auth.py", ["test_*.py", "*.txt"]) is True
    assert _matches("auth.py",      ["test_*.py", "*.txt"]) is False


# --- build_manifest ---

def test_manifest_single_file(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("line1\nline2\nline3\n")
    manifest = build_manifest(str(f))
    assert str(f) in manifest
    assert manifest[str(f)] == (1, 3)


def test_manifest_directory(tmp_path):
    (tmp_path / "a.py").write_text("x\ny\n")
    (tmp_path / "b.py").write_text("a\nb\nc\n")
    manifest = build_manifest(str(tmp_path))
    keys = list(manifest.keys())
    assert any("a.py" in k for k in keys)
    assert any("b.py" in k for k in keys)
    assert manifest[str(tmp_path / "a.py")] == (1, 2)
    assert manifest[str(tmp_path / "b.py")] == (1, 3)


def test_manifest_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("code\n")
    manifest = build_manifest(str(tmp_path))
    assert any("deep.py" in k for k in manifest.keys())


def test_manifest_include_filter(tmp_path):
    (tmp_path / "main.py").write_text("x\n")
    (tmp_path / "style.css").write_text("body{}\n")
    manifest = build_manifest(str(tmp_path), include=["*.py"])
    assert any("main.py"   in k for k in manifest.keys())
    assert not any("style.css" in k for k in manifest.keys())


def test_manifest_exclude_filter(tmp_path):
    (tmp_path / "main.py").write_text("x\n")
    (tmp_path / "main.min.js").write_text("!min\n")
    manifest = build_manifest(str(tmp_path), exclude=["*.min.js"])
    assert any("main.py"      in k for k in manifest.keys())
    assert not any("main.min.js" in k for k in manifest.keys())


def test_manifest_skips_hidden_dirs(tmp_path):
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("data\n")
    manifest = build_manifest(str(tmp_path))
    assert not any(".git" in k for k in manifest.keys())


def test_manifest_skips_empty_files(tmp_path):
    (tmp_path / "empty.py").write_text("")
    manifest = build_manifest(str(tmp_path))
    assert not any("empty.py" in k for k in manifest.keys())
