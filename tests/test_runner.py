"""runner.py 테스트 — fake runner로만 claude 호출을 검증한다 (ADR-004). 실제 claude는 실행하지 않는다."""

import json
import subprocess
import threading

import pytest

from pr_reviewer.models import AgentResult, Finding
from pr_reviewer.runner import ClaudeError, run_claude, run_parallel


class FakeRunner:
    """호출된 (args, input)을 기록하고, 고정 응답(CompletedProcess 또는 던질 예외)을 돌려준다."""

    def __init__(self, response):
        self.response = response
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, input=None):
        self.calls.append((list(args), input))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


def result_json(**overrides) -> str:
    data = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "리뷰 텍스트",
        "structured_output": None,
        "permission_denials": [],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


SCHEMA = {"type": "object", "properties": {"findings": {"type": "array"}}}


# --- 명령 인자 구성 ---


def test_minimal_command_without_options():
    runner = FakeRunner(proc(result_json()))

    run_claude("프롬프트", runner=runner)

    assert runner.calls[0][0] == ["claude", "-p", "--output-format", "json"]


def test_command_with_schema_and_tools():
    runner = FakeRunner(proc(result_json(structured_output={"findings": []})))

    run_claude("p", schema=SCHEMA, allowed_tools=["Read"], disallowed_tools=["Bash", "Edit", "Write"],
               runner=runner)

    assert runner.calls[0][0] == [
        "claude", "-p", "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
        "--allowedTools", "Read",
        "--disallowedTools", "Bash", "Edit", "Write",
    ]


def test_command_with_args_prompt_and_allowed_tools():
    runner = FakeRunner(proc(result_json()))

    run_claude(None, args_prompt="/code-review low https://github.com/o/r/pull/1",
               allowed_tools=["Bash(gh pr diff:*)", "Bash(gh pr view:*)"],
               disallowed_tools=["Edit", "Write"], runner=runner)

    args, stdin = runner.calls[0]
    assert args == [
        "claude", "-p", "/code-review low https://github.com/o/r/pull/1",
        "--output-format", "json",
        "--allowedTools", "Bash(gh pr diff:*)", "Bash(gh pr view:*)",
        "--disallowedTools", "Edit", "Write",
    ]
    assert stdin is None


def test_prompt_is_passed_via_stdin_not_args():
    prompt = "긴 diff 프롬프트\n" + "+x\n" * 1000
    runner = FakeRunner(proc(result_json()))

    run_claude(prompt, runner=runner)

    args, stdin = runner.calls[0]
    assert stdin == prompt
    assert all(prompt not in a for a in args)


# --- 결과 반환 ---


def test_returns_structured_output_when_schema_given():
    out = {"findings": [{"path": "a.py", "line": 3}]}
    runner = FakeRunner(proc(result_json(structured_output=out)))

    assert run_claude("p", schema=SCHEMA, runner=runner) == out


def test_returns_result_text_without_schema():
    runner = FakeRunner(proc(result_json(result="## 리뷰\n- 문제 1")))

    assert run_claude("p", runner=runner) == "## 리뷰\n- 문제 1"


# --- 오류 → ClaudeError ---


def test_nonzero_returncode_raises():
    runner = FakeRunner(proc("", code=2, stderr="auth failed"))

    with pytest.raises(ClaudeError, match="auth failed"):
        run_claude("p", runner=runner)


def test_broken_json_raises():
    runner = FakeRunner(proc("not json {"))

    with pytest.raises(ClaudeError):
        run_claude("p", runner=runner)


def test_is_error_raises():
    runner = FakeRunner(proc(result_json(is_error=True, result="rate limited")))

    with pytest.raises(ClaudeError, match="rate limited"):
        run_claude("p", runner=runner)


def test_non_success_subtype_raises():
    runner = FakeRunner(proc(result_json(subtype="error_max_turns")))

    with pytest.raises(ClaudeError, match="error_max_turns"):
        run_claude("p", runner=runner)


def test_structured_output_null_with_schema_raises():
    runner = FakeRunner(proc(result_json(structured_output=None)))

    with pytest.raises(ClaudeError, match="structured_output"):
        run_claude("p", schema=SCHEMA, runner=runner)


def test_permission_denials_raise_with_tool_name():
    denials = [{"tool_name": "Bash", "tool_use_id": "t1", "tool_input": {"command": "gh api"}}]
    runner = FakeRunner(proc(result_json(result="리뷰를 하지 못했습니다", permission_denials=denials)))

    with pytest.raises(ClaudeError, match="Bash"):
        run_claude(None, args_prompt="/code-review low u", runner=runner)


def test_timeout_is_wrapped():
    runner = FakeRunner(subprocess.TimeoutExpired(["claude"], 900))

    with pytest.raises(ClaudeError, match="timed out|TimeoutExpired"):
        run_claude("p", runner=runner)


# --- run_parallel ---


def test_run_parallel_preserves_key_order():
    tasks = {
        "structural_test": lambda: AgentResult(category="structural_test"),
        "security": lambda: AgentResult(category="security"),
        "code_review": lambda: AgentResult(category="code_review"),
    }

    results = run_parallel(tasks)

    assert [r.category for r in results] == ["structural_test", "security", "code_review"]


def test_run_parallel_isolates_task_failure():
    finding = Finding(category="code_review", path="a.py", line=1, severity="minor", title="t", body="b")

    def boom():
        raise ClaudeError("exit 1")

    tasks = {
        "structural_test": lambda: AgentResult(category="structural_test", skipped_reason="no failures"),
        "security": boom,
        "code_review": lambda: AgentResult(category="code_review", findings=(finding,)),
    }

    results = run_parallel(tasks)

    assert results[0] == AgentResult(category="structural_test", skipped_reason="no failures")
    assert results[1] == AgentResult(category="security", error="ClaudeError: exit 1")
    assert results[2].findings == (finding,)
    assert results[2].error is None


def test_run_parallel_runs_tasks_concurrently():
    barrier = threading.Barrier(2, timeout=5)

    def task(category):
        def run():
            barrier.wait()  # 두 task가 동시에 실행 중이어야만 통과한다
            return AgentResult(category=category)
        return run

    results = run_parallel({"security": task("security"), "code_review": task("code_review")})

    assert [r.error for r in results] == [None, None]
