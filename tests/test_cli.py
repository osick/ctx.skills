import sys, os, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "rlm"))

RLM_PY = os.path.join(os.path.dirname(__file__), "..", "skills", "rlm", "rlm.py")
ECHO_CMD = "echo '<answer>mocked</answer>'"


def run_rlm(args, stdin=None):
    return subprocess.run(
        [sys.executable, RLM_PY] + args,
        input=stdin, capture_output=True, text=True
    )


def test_cli_file_input(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello\n")
    r = run_rlm(["--query", "q", "--input", str(f), "--llm-cmd", ECHO_CMD])
    assert r.returncode == 0
    assert "mocked" in r.stdout


def test_cli_directory_input(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    r = run_rlm(["--query", "q", "--input", str(tmp_path), "--llm-cmd", ECHO_CMD])
    assert r.returncode == 0
    assert "mocked" in r.stdout


def test_cli_stdin_input(tmp_path):
    r = run_rlm(["--query", "q", "--input", "-", "--llm-cmd", ECHO_CMD], stdin="hello from stdin")
    assert r.returncode == 0
    assert "mocked" in r.stdout


def test_cli_include_filter(tmp_path):
    (tmp_path / "main.py").write_text("x\n")
    (tmp_path / "style.css").write_text("body{}\n")
    r = run_rlm([
        "--query", "q", "--input", str(tmp_path),
        "--llm-cmd", ECHO_CMD, "--include", "*.py"
    ])
    assert r.returncode == 0


def test_cli_empty_manifest_exits_nonzero(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = run_rlm(["--query", "q", "--input", str(empty), "--llm-cmd", ECHO_CMD])
    assert r.returncode != 0
