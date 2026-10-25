"""github.py 테스트 — fake runner로만 gh 호출을 검증한다 (ADR-004). 실제 gh는 실행하지 않는다."""

import json
import subprocess
from pathlib import Path

import pytest

from pr_reviewer.github import (
    GhError,
    current_user,
    download_junit_reports,
    fetch_diff,
    fetch_pull_request,
    post_issue_comment,
    post_review,
)
from pr_reviewer.models import InlineComment, PullRequest

PR = PullRequest(
    owner="octo",
    repo="demo",
    number=7,
    head_sha="abc123",
    author="alice",
    url="https://github.com/octo/demo/pull/7",
)


class FakeRunner:
    """호출된 (args, input)을 기록하고, 응답 목록을 순서대로 돌려준다. 응답은 CompletedProcess 또는 callable(args)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, input=None):
        self.calls.append((list(args), input))
        resp = self.responses.pop(0)
        if callable(resp):
            resp = resp(args)
        return resp


def ok(stdout: str = "", args=None) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args or [], 0, stdout=stdout, stderr="")


def fail(stderr: str = "boom", code: int = 1) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout="", stderr=stderr)


# --- 조회 (R1) ---


def test_fetch_pull_request_parses_meta():
    payload = {
        "head": {"sha": "abc123"},
        "user": {"login": "alice"},
        "html_url": "https://github.com/octo/demo/pull/7",
    }
    runner = FakeRunner(ok(json.dumps(payload)))

    pr = fetch_pull_request("octo", "demo", 7, runner=runner)

    assert pr == PR
    assert runner.calls[0][0] == ["gh", "api", "repos/octo/demo/pulls/7"]


def test_fetch_diff_returns_stdout():
    diff = "diff --git a/x.py b/x.py\n+한글\n"
    runner = FakeRunner(ok(diff))

    assert fetch_diff("octo", "demo", 7, runner=runner) == diff
    assert runner.calls[0][0] == ["gh", "pr", "diff", "7", "-R", "octo/demo"]


def test_current_user_returns_login():
    runner = FakeRunner(ok(json.dumps({"login": "bob", "id": 1})))

    assert current_user(runner=runner) == "bob"
    assert runner.calls[0][0] == ["gh", "api", "user"]


@pytest.mark.parametrize(
    "call",
    [
        lambda r: fetch_pull_request("octo", "demo", 7, runner=r),
        lambda r: fetch_diff("octo", "demo", 7, runner=r),
        lambda r: current_user(runner=r),
        lambda r: post_review(PR, "COMMENT", "b", [], runner=r),
        lambda r: post_issue_comment(PR, "b", runner=r),
    ],
)
def test_nonzero_exit_raises_gh_error(call):
    runner = FakeRunner(fail("HTTP 404: Not Found"))

    with pytest.raises(GhError) as exc:
        call(runner)

    assert "HTTP 404: Not Found" in str(exc.value)
    assert "gh" in str(exc.value)


# --- JUnit artifact (R2) ---


def _runs(*runs) -> subprocess.CompletedProcess:
    return ok(json.dumps(list(runs)))


def test_download_selects_latest_completed_run(tmp_path):
    runs = _runs(
        {"databaseId": 1, "status": "completed", "conclusion": "failure", "createdAt": "2026-10-25T01:00:00Z"},
        {"databaseId": 2, "status": "in_progress", "conclusion": "", "createdAt": "2026-10-25T03:00:00Z"},
        {"databaseId": 3, "status": "completed", "conclusion": "success", "createdAt": "2026-10-25T02:00:00Z"},
    )
    runner = FakeRunner(runs, ok())

    download_junit_reports(PR, "junit-results", tmp_path, runner=runner)

    assert runner.calls[0][0] == [
        "gh", "run", "list", "-R", "octo/demo", "--commit", "abc123",
        "--json", "databaseId,status,conclusion,createdAt",
    ]
    assert runner.calls[1][0] == [
        "gh", "run", "download", "3", "-R", "octo/demo", "-n", "junit-results", "-D", str(tmp_path),
    ]


def test_download_no_runs_returns_empty(tmp_path):
    runner = FakeRunner(_runs())

    assert download_junit_reports(PR, "junit-results", tmp_path, runner=runner) == []
    assert len(runner.calls) == 1


def test_download_only_incomplete_runs_returns_empty(tmp_path):
    runner = FakeRunner(
        _runs({"databaseId": 9, "status": "queued", "conclusion": "", "createdAt": "2026-10-25T01:00:00Z"})
    )

    assert download_junit_reports(PR, "junit-results", tmp_path, runner=runner) == []
    assert len(runner.calls) == 1


def test_download_failure_returns_empty(tmp_path):
    runner = FakeRunner(
        _runs({"databaseId": 1, "status": "completed", "conclusion": "success", "createdAt": "2026-10-25T01:00:00Z"}),
        fail("no artifact matches any of the names or patterns provided"),
    )

    assert download_junit_reports(PR, "junit-results", tmp_path, runner=runner) == []


def test_run_list_failure_raises(tmp_path):
    runner = FakeRunner(fail("HTTP 403: Resource not accessible"))

    with pytest.raises(GhError) as exc:
        download_junit_reports(PR, "junit-results", tmp_path, runner=runner)

    assert "HTTP 403" in str(exc.value)


def test_download_collects_xml_paths_recursively_sorted(tmp_path):
    def create_files(args):
        dest = Path(args[args.index("-D") + 1])
        (dest / "sub").mkdir(parents=True)
        (dest / "sub" / "b.xml").write_text("<testsuite/>", encoding="utf-8")
        (dest / "a.xml").write_text("<testsuite/>", encoding="utf-8")
        (dest / "notes.txt").write_text("x", encoding="utf-8")
        return ok()

    runner = FakeRunner(
        _runs({"databaseId": 1, "status": "completed", "conclusion": "failure", "createdAt": "2026-10-25T01:00:00Z"}),
        create_files,
    )

    paths = download_junit_reports(PR, "junit-results", tmp_path, runner=runner)

    assert paths == [tmp_path / "a.xml", tmp_path / "sub" / "b.xml"]


# --- 게시 (R5) ---


def test_post_review_payload():
    runner = FakeRunner(ok("{}"))
    comments = [InlineComment(path="src/app.py", line=12, body="[보안] 입력 검증 누락")]

    post_review(PR, "REQUEST_CHANGES", "리뷰 요약", comments, runner=runner)

    args, stdin = runner.calls[0]
    assert args == ["gh", "api", "repos/octo/demo/pulls/7/reviews", "--method", "POST", "--input", "-"]
    assert json.loads(stdin) == {
        "commit_id": "abc123",
        "event": "REQUEST_CHANGES",
        "body": "리뷰 요약",
        "comments": [{"path": "src/app.py", "line": 12, "side": "RIGHT", "body": "[보안] 입력 검증 누락"}],
    }
    assert "입력 검증 누락" in stdin  # ensure_ascii=False


def test_post_review_sends_comments_unfiltered():
    runner = FakeRunner(ok("{}"))
    comments = [InlineComment("a.py", 1, "x"), InlineComment("b.py", 999, "y")]

    post_review(PR, "COMMENT", "", comments, runner=runner)

    sent = json.loads(runner.calls[0][1])["comments"]
    assert [(c["path"], c["line"]) for c in sent] == [("a.py", 1), ("b.py", 999)]


@pytest.mark.parametrize("event", ["APPROVE", "comment", "", "PENDING"])
def test_post_review_rejects_invalid_event(event):
    runner = FakeRunner()

    with pytest.raises(ValueError):
        post_review(PR, event, "b", [], runner=runner)

    assert runner.calls == []


def test_post_issue_comment_payload():
    runner = FakeRunner(ok("{}"))

    post_issue_comment(PR, "## 요약\n- 한국어", runner=runner)

    args, stdin = runner.calls[0]
    assert args == ["gh", "api", "repos/octo/demo/issues/7/comments", "--method", "POST", "--input", "-"]
    assert json.loads(stdin) == {"body": "## 요약\n- 한국어"}
    assert "한국어" in stdin
