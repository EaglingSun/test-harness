"""loop.fix --mode real (R13, ADR-007). fake runner만 쓴다 — 실제 claude/git 실행 금지 (ADR-004)."""

import subprocess

import pytest

from loop import fix
from loop.contract import read_stage, write_stage

SHA = "d" * 40
ID1 = "test_diag_log::SR-011_non_numeric_returns_minus1"
MSG1 = "tests/test_diag_log.c:15: -1 == dl_parse_threshold(\"abc\") (expected -1, actual 0)"
ID2 = "test_sensor_filter::SR-009_latest_after_push"
MSG2 = "tests/test_sensor_filter.c:18: 11 == sf_latest() (expected 11, actual 0)"
OTHER_MSG = "tests/test_speed_monitor.c:13: listed failure"
REQ = "# 요구사항\nSR-011 숫자가 아니면 -1 을 돌려준다.\n"

XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="test_diag_log" tests="2" failures="1">
    <testcase classname="test_diag_log" name="SR-011_non_numeric_returns_minus1">
      <failure message="{MSG1.replace('"', '&quot;')}">detail</failure>
    </testcase>
    <testcase classname="test_diag_log" name="SR-011_numeric_parses"/>
  </testsuite>
  <testsuite name="test_sensor_filter" tests="1" failures="1">
    <testcase classname="test_sensor_filter" name="SR-009_latest_after_push">
      <error message="{MSG2}">detail</error>
    </testcase>
  </testsuite>
  <testsuite name="test_speed_monitor" tests="1" failures="1">
    <testcase classname="test_speed_monitor" name="SEC3_speed_0_is_none">
      <failure message="{OTHER_MSG}">detail</failure>
    </testcase>
  </testsuite>
</testsuites>
"""

ARGS = ["--pr", "7", "--head-ref", "feat-x", "--base-ref", "origin/master", "--mode", "real"]


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class GitFake:
    """git 하위 명령(-C <ws> 와 -c 옵션 다음 첫 단어) → 응답. 호출을 기록한다."""

    def __init__(self, status: str = "", log: str = "", over: dict | None = None):
        self.table = {"log": proc(log), "status": proc(status), "checkout": proc(), "clean": proc(),
                      "add": proc(), "commit": proc(), "push": proc(), "rev-parse": proc(SHA + "\n")}
        self.table.update(over or {})
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(list(args))
        assert args[0] == "git" and args[1] == "-C"
        sub = args[3:]
        while sub and sub[0] == "-c":
            sub = sub[2:]
        return self.table[sub[0]]

    def subs(self) -> list[str]:
        out = []
        for c in self.calls:
            sub = c[3:]
            while sub and sub[0] == "-c":
                sub = sub[2:]
            out.append(sub[0])
        return out


class ClaudeFake:
    def __init__(self, response=None):
        self.response = response if response is not None else proc('{"type":"result","is_error":false}')
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, input=None):
        self.calls.append((list(args), input))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@pytest.fixture
def ws(tmp_path):
    out = tmp_path / "out"
    write_stage(out, "test", {"stage": "test", "status": "ok", "make_outcome": "failure", "total": 4,
                              "failed": [ID1, ID2, "test_speed_monitor::SEC3_speed_0_is_none"],
                              "unexpected": [ID1, ID2], "fixed": [], "missing": [], "head_sha": SHA,
                              "expected_base": ["test_speed_monitor::SEC3_speed_0_is_none"],
                              "expected_head": []})
    (out / "test_all.xml").write_text(XML, encoding="utf-8")
    (tmp_path / "test_ref").mkdir()
    (tmp_path / "test_ref" / "요구사항.md").write_text(REQ, encoding="utf-8")
    return tmp_path


def run(ws, git: GitFake, claude: ClaudeFake) -> int:
    return fix.main(["--workspace", str(ws), *ARGS], runner=git, claude_runner=claude)


def test_claude_argv_and_prompt(ws):
    git, claude = GitFake(status=" M src/diag_log.c\n"), ClaudeFake()
    assert run(ws, git, claude) == 0
    assert len(claude.calls) == 1
    argv, prompt = claude.calls[0]
    assert argv == ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                    "--allowedTools", "Read", "Edit", "Glob", "Grep", "--disallowedTools", "Bash", "Write"]
    for text in (ID1, ID2, MSG1, MSG2, REQ.strip()):
        assert text in prompt
    assert OTHER_MSG not in prompt  # unexpected 가 아닌 실패는 넣지 않는다
    assert "`src/`·`include/` 아래 파일만" in prompt
    assert "tests/expected_failures.txt" in prompt and "빌드·실행은 하지 마라" in prompt


def test_default_claude_runner_uses_workspace_cwd(ws, monkeypatch):
    seen = {}

    def fake_run_process(args, input=None, timeout=900, cwd=None):
        seen.update(args=args, timeout=timeout, cwd=cwd)
        return proc("{}")

    monkeypatch.setattr(fix, "run_process", fake_run_process)
    git = GitFake(status="")
    assert fix.main(["--workspace", str(ws), *ARGS], runner=git) == 0
    assert seen["args"][0] == "claude" and seen["cwd"] == str(ws) and seen["timeout"] == 600


def test_no_change_is_no_action(ws):
    git, claude = GitFake(status=""), ClaudeFake()
    assert run(ws, git, claude) == 0
    data = read_stage(ws / "out", "fix")
    assert data["action"] == "NO_ACTION" and data["reason"] == "Fix 가 변경하지 않음"
    assert data["status"] == "ok" and data["mode"] == "real" and data["changed_files"] == []
    assert "commit" not in git.subs() and "push" not in git.subs()


def test_expected_failures_change_is_reverted(ws):
    git = GitFake(status=" M src/diag_log.c\n M tests/expected_failures.txt\n")
    assert run(ws, git, ClaudeFake()) == 1
    w = str(ws)
    assert ["git", "-C", w, "checkout", "--", "."] in git.calls
    assert ["git", "-C", w, "clean", "-fd", "--", "."] in git.calls
    assert "commit" not in git.subs() and "push" not in git.subs() and "add" not in git.subs()
    data = read_stage(ws / "out", "fix")
    assert data["action"] == "FAILED" and data["status"] == "error"
    assert "tests/expected_failures.txt" in data["reason"]


@pytest.mark.parametrize("status", [
    "?? newfile.c\n",                              # 새 파일
    "R  src/a.c -> tests/a.c\n",                   # 이름 바꿔 밖으로
    ' M "tests/\\352\\270\\200.c"\n',             # git 이 따옴표로 감싼 경로
    " M srcx/a.c\n",                               # 접두어만 닮은 경로
])
def test_outside_paths_fail(ws, status):
    git = GitFake(status=status)
    assert run(ws, git, ClaudeFake()) == 1
    assert "checkout" in git.subs() and "commit" not in git.subs()
    assert read_stage(ws / "out", "fix")["action"] == "FAILED"


def test_src_include_change_commits_and_pushes(ws):
    git = GitFake(status=" M src/diag_log.c\n?? include/new.h\n")
    assert run(ws, git, ClaudeFake()) == 0
    w = str(ws)
    assert ["git", "-C", w, "add", "--", "src/diag_log.c", "include/new.h"] in git.calls
    commit = [c for c in git.calls if "commit" in c][0]
    assert "user.name=loop-bot" in commit
    assert commit[commit.index("commit"):] == ["commit", "-m", "fix(loop): auto-fix for PR #7", "-m", "Loop-Fix: 1"]
    assert ["git", "-C", w, "push", "origin", "HEAD:feat-x"] in git.calls
    assert "checkout" not in git.subs()
    data = read_stage(ws / "out", "fix")
    assert data["action"] == "COMMITTED" and data["commit_sha"] == SHA and data["status"] == "ok"
    assert data["changed_files"] == ["src/diag_log.c", "include/new.h"]


@pytest.mark.parametrize("response, out_text, err_text", [
    (proc(stdout="partial-out" + "x" * 3000, code=1, stderr="boom"), "partial-out", "boom"),
    (subprocess.TimeoutExpired(["claude"], 600, output="slow-out", stderr="slow-err"), "slow-out", "slow-err"),
])
def test_claude_failure_is_failed_with_raw(ws, response, out_text, err_text):
    git = GitFake(status=" M src/diag_log.c\n")
    assert run(ws, git, ClaudeFake(response)) == 1
    data = read_stage(ws / "out", "fix")
    assert data["action"] == "FAILED" and data["status"] == "error"
    raw = (ws / "out" / "fix-claude-raw.txt").read_text(encoding="utf-8")
    assert out_text in raw and err_text in raw
    assert "x" * 2001 not in raw
    assert "status" not in git.subs() and "commit" not in git.subs()


def test_fix_limit_skips_claude(ws):
    git, claude = GitFake(log="fix(loop): auto-fix\n\nLoop-Fix: 1\n"), ClaudeFake()
    assert run(ws, git, claude) == 0
    assert claude.calls == []
    assert git.subs() == ["log"]
    assert read_stage(ws / "out", "fix")["action"] == "NO_ACTION"


def test_missing_requirements_fails_without_claude(ws):
    (ws / "test_ref" / "요구사항.md").unlink()
    git, claude = GitFake(), ClaudeFake()
    assert run(ws, git, claude) == 1
    assert claude.calls == []
    assert read_stage(ws / "out", "fix")["action"] == "FAILED"
