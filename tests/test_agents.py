"""agents.py 테스트 — fake runner로만 claude 호출을 검증한다 (ADR-004). 실제 claude는 실행하지 않는다."""

import json
import subprocess
import threading

import pytest

from pr_reviewer.agents import (
    FINDINGS_SCHEMA,
    review_code,
    review_security,
    review_structural_tests,
    run_all_agents,
)
from pr_reviewer.models import AgentResult, Finding, PullRequest, TestFailure, TestReport
from pr_reviewer.runner import ClaudeError

PR = PullRequest(owner="o", repo="r", number=7, head_sha="abc123", author="dev",
                 url="https://github.com/o/r/pull/7")
DIFF = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = eval(input())\n"
REVIEW_TEXT = "1. app.py:2 — off-by-one in loop bound\n2. app.py:2 — SQL injection via user input"
FAILURE = TestFailure(name="test_bound", classname="tests.test_app", kind="failure",
                      message="AssertionError: expected 10 got 9", details="Traceback ...",
                      file="tests/test_app.py", line=12)


def item(category: str, **overrides) -> dict:
    data = {
        "category": category, "path": "app.py", "line": 2, "severity": "major",
        "title": "제목", "body": "본문", "failure_scenario": "입력 → 기대 vs 실제", "reachability": "",
    }
    data.update(overrides)
    return data


def result_json(**overrides) -> str:
    data = {"type": "result", "subtype": "success", "is_error": False, "result": "",
            "structured_output": None, "permission_denials": []}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class FakeRunner:
    """args/stdin으로 에이전트·단계를 판별해 고정 응답을 돌려준다. 호출 (args, stdin)을 기록한다.

    responses 키: "A", "B", "C1"(code-review 텍스트), "C2"(JSON 변환). 값은 findings list 또는 CompletedProcess.
    """

    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[tuple[str, list[str], str | None]] = []
        self.lock = threading.Lock()

    @staticmethod
    def classify(args: list[str], stdin: str | None) -> str:
        if any(a.startswith("/code-review") for a in args):
            return "C1"
        if "'구조 기반 테스트' 관점" in (stdin or ""):
            return "A"
        if "'보안' 관점" in (stdin or ""):
            return "B"
        return "C2"

    def __call__(self, args, input=None):
        kind = self.classify(args, input)
        with self.lock:
            self.calls.append((kind, list(args), input))
        resp = self.responses.get(kind, REVIEW_TEXT if kind == "C1" else [])
        if isinstance(resp, subprocess.CompletedProcess):
            return resp
        if kind == "C1":
            return proc(result_json(result=resp))
        return proc(result_json(structured_output={"findings": resp}))

    def call(self, kind: str) -> tuple[list[str], str | None]:
        matches = [(a, s) for k, a, s in self.calls if k == kind]
        assert len(matches) == 1, f"{kind} 호출 횟수: {len(matches)}"
        return matches[0]


def disallowed(args: list[str]) -> list[str]:
    i = args.index("--disallowedTools")
    return args[i + 1:]


# --- A: 구조 기반 테스트 ---


def test_structural_skips_without_report():
    runner = FakeRunner()

    result = review_structural_tests(PR, DIFF, None, runner)

    assert result == AgentResult(category="structural_test", skipped_reason="테스트 결과 없음")
    assert runner.calls == []


def test_structural_skips_when_no_failures():
    runner = FakeRunner()

    result = review_structural_tests(PR, DIFF, TestReport(total=5, failures=()), runner)

    assert result == AgentResult(category="structural_test", skipped_reason="실패 테스트 0건 (총 5건)")
    assert runner.calls == []


def test_structural_prompt_contains_failures_and_diff():
    runner = FakeRunner(A=[item("structural_test", severity="critical")])

    result = review_structural_tests(PR, DIFF, TestReport(total=3, failures=(FAILURE,)), runner)

    args, stdin = runner.call("A")
    for text in ("test_bound", "tests.test_app", "failure", "AssertionError: expected 10 got 9",
                 "Traceback ...", "tests/test_app.py", "12", DIFF):
        assert text in stdin
    assert args[args.index("--json-schema") + 1] == json.dumps(FINDINGS_SCHEMA)
    assert disallowed(args) == ["Bash", "Edit", "Write"]
    assert "--allowedTools" not in args
    assert result.findings == (Finding(category="structural_test", path="app.py", line=2,
                                       severity="critical", title="제목", body="본문",
                                       failure_scenario="입력 → 기대 vs 실제", reachability=""),)


STRUCTURAL_LOCATION_PHRASES = (
    "원인이 된 제품 코드",
    "테스트 코드(assert/expect 줄, 테스트 파일)의 위치를 적지 마라",
    "원인 코드가 diff 밖이거나(이 PR이 바꾸지 않은 코드) 특정할 수 없으면 line을 null로 둔다",
    "실패한 테스트 파일 경로",
    "테스트 코드 자체가 이 PR에서 잘못 작성되어 실패한 경우",
)


def test_structural_prompt_has_cause_location_rules():
    runner = FakeRunner(A=[])

    review_structural_tests(PR, DIFF, TestReport(total=3, failures=(FAILURE,)), runner)

    _, stdin = runner.call("A")
    for text in STRUCTURAL_LOCATION_PHRASES:
        assert text in stdin


def test_security_prompt_has_no_structural_location_rules():
    runner = FakeRunner(B=[])

    review_security(PR, DIFF, runner)

    _, stdin = runner.call("B")
    for text in STRUCTURAL_LOCATION_PHRASES:
        assert text not in stdin


# --- B: 보안 ---


def test_security_prompt_and_tools():
    runner = FakeRunner(B=[item("security")])

    result = review_security(PR, DIFF, runner)

    args, stdin = runner.call("B")
    assert DIFF in stdin
    assert "보안 외 문제는 보고하지 마라" in stdin
    assert "failure_scenario" in stdin and "reachability" in stdin
    assert disallowed(args) == ["Bash", "Edit", "Write"]
    assert "--allowedTools" not in args
    assert "--json-schema" in args
    assert [f.category for f in result.findings] == ["security"]


def test_security_drops_other_category_items():
    runner = FakeRunner(B=[item("security", title="보안"), item("code_review", title="코드"),
                           item("structural_test", title="테스트")])

    result = review_security(PR, DIFF, runner)

    assert [f.title for f in result.findings] == ["보안"]


def test_broken_items_are_dropped():
    good = item("security", line=None, title="ok")
    broken = [
        "not a dict",
        {k: v for k, v in item("security").items() if k != "body"},  # 필수 필드 누락
        {k: v for k, v in item("security").items() if k != "line"},  # line 키 누락
        item("security", line="2"),  # line 타입 오류
        item("security", line=True),  # bool은 정수가 아님
        item("security", severity="blocker"),  # 등급 오류
        item("security", path=""),  # 빈 경로
        item("security", title=None),  # 타입 오류
    ]
    runner = FakeRunner(B=[*broken, good])

    result = review_security(PR, DIFF, runner)

    assert [(f.title, f.line) for f in result.findings] == [("ok", None)]


def test_findings_not_a_list_yields_empty():
    runner = FakeRunner(B=proc(result_json(structured_output={"findings": "oops"})))

    assert review_security(PR, DIFF, runner).findings == ()


# --- C: 코드 리뷰 2단계 ---


def test_code_review_stage1_command():
    runner = FakeRunner()

    review_code(PR, runner)

    args, stdin = runner.call("C1")
    assert stdin is None
    assert args[:3] == ["claude", "-p", "/code-review low https://github.com/o/r/pull/7"]
    assert "--json-schema" not in args
    i = args.index("--allowedTools")
    assert args[i + 1:i + 3] == ["Bash(gh pr diff:*)", "Bash(gh pr view:*)"]
    assert disallowed(args) == ["Edit", "Write"]
    assert not any("gh api" in a for a in args)
    assert not any("--comment" in a or "--fix" in a for a in args)


def test_code_review_stage2_converts_stage1_text():
    runner = FakeRunner(C2=[item("code_review", title="off-by-one"), item("security", title="sqli")])

    result = review_code(PR, runner)

    args, stdin = runner.call("C2")
    assert REVIEW_TEXT in stdin
    assert "보안 관련 지적" in stdin and "제외" in stdin
    assert "새 지적을 만들지 마라" in stdin
    assert "(none)" in stdin
    assert args[args.index("--json-schema") + 1] == json.dumps(FINDINGS_SCHEMA)
    assert disallowed(args) == ["Bash", "Edit", "Write"]
    assert [f.title for f in result.findings] == ["off-by-one"]
    assert result.category == "code_review"


def test_code_review_stage1_failure_skips_stage2():
    runner = FakeRunner(C1=proc("", code=1, stderr="boom"))

    with pytest.raises(ClaudeError, match="boom"):
        review_code(PR, runner)
    assert [k for k, _, _ in runner.calls] == ["C1"]


# --- run_all_agents ---


def test_run_all_agents_partial_failure():
    runner = FakeRunner(A=[item("structural_test")], B=[item("security")],
                        C1=proc("", code=1, stderr="boom"))

    results = run_all_agents(PR, DIFF, TestReport(total=1, failures=(FAILURE,)), runner)

    assert [r.category for r in results] == ["structural_test", "security", "code_review"]
    a, b, c = results
    assert a.error is None and len(a.findings) == 1
    assert b.error is None and len(b.findings) == 1
    assert c.findings == () and c.error.startswith("ClaudeError")


def test_run_all_agents_skips_a_without_report():
    runner = FakeRunner(B=[item("security")], C2=[item("code_review")])

    results = run_all_agents(PR, DIFF, None, runner)

    assert results[0] == AgentResult(category="structural_test", skipped_reason="테스트 결과 없음")
    assert sorted(k for k, _, _ in runner.calls) == ["B", "C1", "C2"]
