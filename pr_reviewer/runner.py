"""claude CLI headless 실행, JSON 결과 파싱, 병렬 실행 + 부분 실패 처리 (R3, ADR-002, ADR-004)."""

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Mapping, Sequence

from pr_reviewer.models import AgentResult
from pr_reviewer.proc import Runner, run_process


class ClaudeError(Exception):
    """claude 실행 실패: 비정상 종료, JSON 파싱 실패, 에러 결과, 권한 거부, timeout."""


def run_claude(prompt: str | None, *, args_prompt: str | None = None,
               schema: dict | None = None,
               allowed_tools: Sequence[str] = (), disallowed_tools: Sequence[str] = (),
               runner: Runner = run_process) -> dict | str:
    """claude -p 1회 실행. schema가 있으면 structured_output(dict), 없으면 result(str) 반환.

    prompt는 stdin으로 넘긴다(Windows 명령줄 길이 제한). args_prompt는 짧은 슬래시 명령 전용이다.
    """
    args = ["claude", "-p", *([args_prompt] if args_prompt else []), "--output-format", "json"]
    if schema is not None:
        args += ["--json-schema", json.dumps(schema)]
    if allowed_tools:
        args += ["--allowedTools", *allowed_tools]
    if disallowed_tools:
        args += ["--disallowedTools", *disallowed_tools]

    try:
        proc = runner(args, prompt)
    except subprocess.TimeoutExpired as e:
        raise ClaudeError(f"claude timed out after {e.timeout}s") from e
    if proc.returncode != 0:
        raise ClaudeError(f"claude failed (exit {proc.returncode}): {(proc.stderr or '').strip()}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"claude output is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise ClaudeError(f"claude output is not a JSON object: {type(data).__name__}")

    if data.get("is_error"):
        raise ClaudeError(f"claude returned error: {data.get('result')}")
    if data.get("subtype") != "success":
        raise ClaudeError(f"claude result subtype is {data.get('subtype')!r}")
    denials = data.get("permission_denials") or []
    if denials:
        names = sorted({str(d.get("tool_name")) if isinstance(d, dict) else str(d) for d in denials})
        raise ClaudeError(f"claude tool permission denied: {', '.join(names)}")

    if schema is not None:
        output = data.get("structured_output")
        if not isinstance(output, dict):
            raise ClaudeError(f"claude structured_output is not an object: {type(output).__name__}")
        return output
    result = data.get("result")
    if not isinstance(result, str):
        raise ClaudeError(f"claude result is not text: {type(result).__name__}")
    return result


def run_parallel(tasks: Mapping[str, Callable[[], AgentResult]]) -> list[AgentResult]:
    """task들을 ThreadPoolExecutor로 동시에 실행. 결과는 tasks의 키 순서대로 반환.

    task가 예외를 던지면 해당 결과만 AgentResult(error=...)로 바꾸고 나머지는 그대로 진행한다 (R3).
    """
    if not tasks:
        return []
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {key: pool.submit(fn) for key, fn in tasks.items()}
        results = []
        for key, future in futures.items():
            try:
                results.append(future.result())
            except Exception as e:
                results.append(AgentResult(category=key, error=f"{type(e).__name__}: {e}"))
    return results
