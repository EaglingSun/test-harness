"""CLI 조립 테스트 — fake runner로만 gh/claude 호출을 검증한다 (ADR-004). 실제 gh/claude는 실행하지 않는다."""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from pr_reviewer.__main__ import main

PR_JSON = json.dumps({"head": {"sha": "abc123"}, "user": {"login": "dev"},
                      "html_url": "https://github.com/o/r/pull/7"})
DIFF = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = eval(input())\n"
JUNIT_XML = """<?xml version="1.0"?>
<testsuite name="s" tests="2">
  <testcase name="test_ok" classname="tests.test_app"/>
  <testcase name="test_bound" classname="tests.test_app">
    <failure message="AssertionError: expected 10 got 9">Traceback ...</failure>
  </testcase>
</testsuite>
"""
RUNS_JSON = json.dumps([{"databaseId": 42, "status": "completed", "conclusion": "failure",
                         "createdAt": "2026-10-25T00:00:00Z"}])


def item(category: str, **overrides) -> dict:
    data = {"category": category, "path": "app.py", "line": 2, "severity": "major",
            "title": f"{category} 지적", "body": "본문", "failure_scenario": "입력 → 기대 vs 실제",
            "reachability": "정상 호출 흐름"}
    data.update(overrides)
    return data


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


def claude_json(**overrides) -> str:
    data = {"type": "result", "subtype": "success", "is_error": False, "result": "",
            "structured_output": None, "permission_denials": []}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class FakeRunner:
    """args/stdin으로 gh·claude 명령을 판별해 고정 응답을 돌려준다. 호출 (kind, args, stdin)을 기록한다.

    overrides 키: "pr", "diff", "user", "run_list", "run_download", "A", "B", "C1", "C2", "post_review",
    "post_comment". 값이 CompletedProcess면 그대로 반환한다.
    """

    def __init__(self, junit_xml: str | None = JUNIT_XML, **overrides):
        self.junit_xml = junit_xml
        self.overrides = overrides
        self.calls: list[tuple[str, list[str], str | None]] = []
        self.lock = threading.Lock()

    @staticmethod
    def classify(args: list[str], stdin: str | None) -> str:
        if args[0] == "gh":
            if args[1:3] == ["pr", "diff"]:
                return "diff"
            if args[1:3] == ["run", "list"]:
                return "run_list"
            if args[1:3] == ["run", "download"]:
                return "run_download"
            if args[1:3] == ["api", "user"]:
                return "user"
            if "POST" in args:
                return "post_review" if args[2].endswith("/reviews") else "post_comment"
            return "pr"
        if any(a.startswith("/code-review") for a in args):
            return "C1"
        if "'구조 기반 테스트' 관점" in (stdin or ""):
            return "A"
        if "'보안' 관점" in (stdin or ""):
            return "B"
        return "C2"

    def default(self, kind: str, args: list[str]) -> subprocess.CompletedProcess:
        if kind == "pr":
            return proc(PR_JSON)
        if kind == "diff":
            return proc(DIFF)
        if kind == "user":
            return proc(json.dumps({"login": "reviewer"}))
        if kind == "run_list":
            return proc(RUNS_JSON if self.junit_xml is not None else "[]")
        if kind == "run_download":
            dest = Path(args[args.index("-D") + 1])
            (dest / "junit.xml").write_text(self.junit_xml, encoding="utf-8")
            return proc()
        if kind == "A":
            return proc(claude_json(structured_output={"findings": [item("structural_test")]}))
        if kind == "B":
            return proc(claude_json(structured_output={"findings": [item("security")]}))
        if kind == "C1":
            return proc(claude_json(result="1. app.py:2 — off-by-one"))
        if kind == "C2":
            return proc(claude_json(structured_output={"findings": [item("code_review", line=None)]}))
        return proc("{}")  # POST

    def __call__(self, args, input=None):
        kind = self.classify(args, input)
        with self.lock:
            self.calls.append((kind, list(args), input))
        resp = self.overrides.get(kind)
        return resp if isinstance(resp, subprocess.CompletedProcess) else self.default(kind, args)

    def kinds(self) -> list[str]:
        return [k for k, _, _ in self.calls]

    def posts(self) -> list[tuple[str, dict]]:
        return [(k, json.loads(stdin)) for k, _, stdin in self.calls if k.startswith("post_")]


def test_dry_run_prints_payload_without_posting(capsys):
    fake = FakeRunner()
    code = main(["o/r", "7", "--dry-run"], runner=fake)

    assert code == 0
    assert fake.posts() == []
    out = json.loads(capsys.readouterr().out)
    assert out["event"] == "REQUEST_CHANGES"  # A의 line 있는 실패 → critical
    assert out["review_body"]
    assert out["inline"] == [{"path": "app.py", "line": 2, "body": out["inline"][0]["body"]}]
    assert "[구조 기반 테스트]" in out["inline"][0]["body"]
    assert "## PR 리뷰 결과" in out["summary_markdown"]
    assert "총 2건 중 실패 1건" in out["summary_markdown"]
    assert [a["category"] for a in out["agents"]] == ["structural_test", "security", "code_review"]
    assert out["agents"][1]["findings"][0]["title"] == "security 지적"
    assert out["agents"][2]["findings"][0]["line"] is None
    assert all(a["error"] is None and a["skipped_reason"] is None for a in out["agents"])


def test_dry_run_uses_custom_junit_artifact_name(capsys):
    fake = FakeRunner()
    assert main(["o/r", "7", "--dry-run", "--junit-artifact", "my-results"], runner=fake) == 0
    _, args, _ = next(c for c in fake.calls if c[0] == "run_download")
    assert args[args.index("-n") + 1] == "my-results"


def test_default_junit_artifact_name(capsys):
    fake = FakeRunner()
    main(["o/r", "7", "--dry-run"], runner=fake)
    _, args, _ = next(c for c in fake.calls if c[0] == "run_download")
    assert args[args.index("-n") + 1] == "junit-results"


def test_posts_review_then_issue_comment(capsys):
    fake = FakeRunner()
    code = main(["o/r", "7"], runner=fake)

    assert code == 0
    posts = fake.posts()
    assert [k for k, _ in posts] == ["post_review", "post_comment"]
    review, comment = posts[0][1], posts[1][1]
    assert review["event"] == "REQUEST_CHANGES"
    assert review["commit_id"] == "abc123"
    assert [(c["path"], c["line"], c["side"]) for c in review["comments"]] == [("app.py", 2, "RIGHT")]
    assert "## PR 리뷰 결과" in comment["body"]
    out = capsys.readouterr().out
    assert "https://github.com/o/r/pull/7" in out
    assert "REQUEST_CHANGES" in out
    assert "inline=1" in out


def test_no_junit_run_skips_agent_a_and_continues(capsys):
    fake = FakeRunner(junit_xml=None)
    code = main(["o/r", "7"], runner=fake)

    assert code == 0
    assert "A" not in fake.kinds()
    assert "run_download" not in fake.kinds()
    assert {"B", "C1", "C2"} <= set(fake.kinds())
    comment = fake.posts()[1][1]["body"]
    assert "실행하지 않음: 테스트 결과 없음" in comment
    assert "security 지적" in comment


def test_broken_junit_xml_warns_and_continues(capsys):
    fake = FakeRunner(junit_xml="<testsuite><testcase")
    code = main(["o/r", "7", "--dry-run"], runner=fake)

    assert code == 0
    captured = capsys.readouterr()
    assert "junit.xml" in captured.err
    out = json.loads(captured.out)
    assert out["agents"][0]["skipped_reason"] == "테스트 결과 없음"
    assert "A" not in fake.kinds()


def test_one_agent_claude_failure_still_posts(capsys):
    fake = FakeRunner(B=proc(code=1, stderr="boom"))
    code = main(["o/r", "7"], runner=fake)

    assert code == 0
    assert [k for k, _ in fake.posts()] == ["post_review", "post_comment"]
    comment = fake.posts()[1][1]["body"]
    assert "실행 실패:" in comment
    assert "boom" in comment


def test_post_review_failure_posts_summary_with_notice_and_returns_1(capsys):
    fake = FakeRunner(post_review=proc(code=1, stderr="HTTP 422: Unprocessable Entity"))
    code = main(["o/r", "7"], runner=fake)

    assert code == 1
    posts = fake.posts()
    assert [k for k, _ in posts] == ["post_review", "post_comment"]
    body = posts[1][1]["body"]
    assert "## PR 리뷰 결과" in body
    assert body.rstrip().splitlines()[-1].startswith("인라인 리뷰 게시 실패: ")
    assert "HTTP 422" in body


def test_pr_fetch_failure_returns_1_without_posting(capsys):
    fake = FakeRunner(pr=proc(code=1, stderr="HTTP 404: Not Found"))
    code = main(["o/r", "7"], runner=fake)

    assert code == 1
    assert fake.posts() == []
    assert not any(k in ("A", "B", "C1", "C2") for k in fake.kinds())
    captured = capsys.readouterr()
    assert "HTTP 404" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("repo", ["just-repo", "o/r/x", "/r", "o/"])
def test_invalid_repo_argument_exits(repo, capsys):
    fake = FakeRunner()
    with pytest.raises(SystemExit) as exc:
        main([repo, "7"], runner=fake)
    assert exc.value.code != 0
    assert fake.calls == []


def test_non_integer_pr_number_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["o/r", "abc"], runner=FakeRunner())
    assert exc.value.code != 0
