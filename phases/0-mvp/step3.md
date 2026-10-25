# Step 3: agent-runner

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-002: claude CLI headless, 프롬프트는 stdin, 병렬 실행 + 부분 실패 허용
- ADR-004: runner 주입

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `pr_reviewer/models.py` (AgentResult, Category)
- `pr_reviewer/proc.py` (Runner, run_process)
- `pr_reviewer/github.py` (runner 사용·에러 처리 패턴 참고)
- `tests/test_github.py` (fake runner 패턴 참고)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/runner.py`

```python
class ClaudeError(Exception): ...

def run_claude(prompt: str | None, *, args_prompt: str | None = None,
               schema: dict | None = None,
               allowed_tools: Sequence[str] = (), disallowed_tools: Sequence[str] = (),
               runner: Runner = run_process) -> dict | str:
    """claude -p 1회 실행. schema가 있으면 structured_output(dict), 없으면 result(str) 반환."""

def run_parallel(tasks: Mapping[str, Callable[[], AgentResult]]) -> list[AgentResult]:
    """task들을 ThreadPoolExecutor로 동시에 실행. 결과는 tasks의 키 순서대로 반환."""
```

`run_claude` 규칙 (2026-10-25 스파이크로 확인된 CLI 동작):
- 명령: `["claude", "-p", *([args_prompt] if args_prompt else []), "--output-format", "json", *schema_args, *tool_args]`.
  - schema가 있으면 `["--json-schema", json.dumps(schema)]`.
  - allowed_tools가 있으면 `["--allowedTools", *allowed_tools]`, disallowed_tools가 있으면 `["--disallowedTools", *disallowed_tools]`.
- `prompt`는 stdin(runner의 두 번째 인자)으로 넘긴다. 이유: Windows 명령줄 길이 제한(ADR-002). `args_prompt`는 `/code-review low <URL>`처럼 짧은 슬래시 명령 전용이다.
- stdout은 JSON 한 개다: `{"type":"result","subtype":"success","is_error":false,"result":"<텍스트>","structured_output":{...}|null,...}`.
- 다음은 모두 `ClaudeError`: returncode != 0, stdout JSON 파싱 실패, `is_error == true`, `subtype != "success"`, schema가 있는데 `structured_output`이 dict가 아님.
- 출력 JSON의 `permission_denials`가 비어 있지 않으면 `ClaudeError`(거부된 도구 이름 포함). 이유: 스파이크에서 권한 거부 시 리뷰 없이 "리뷰를 못 했다"는 텍스트가 success로 나왔다.
- `subprocess.TimeoutExpired`는 `ClaudeError`로 감싼다.

`run_parallel` 규칙:
- 각 task가 예외를 던지면 `AgentResult(category=<키>, error=f"{예외타입}: {메시지}")`로 바꾼다. 하나의 실패가 다른 task를 취소하거나 전체를 실패시키면 안 된다(R3).
- `max_workers = len(tasks)`.

### `tests/test_runner.py`
- fake runner로만 테스트한다.
- 최소 케이스: 명령 인자 구성(schema/tools/args_prompt 유무), prompt가 stdin으로 전달되고 args에 없음, structured_output 반환, result 텍스트 반환, returncode≠0 / 깨진 JSON / is_error / structured_output null / permission_denials / TimeoutExpired → ClaudeError, run_parallel 순서 보존, 한 task 예외 → 해당 결과만 error·나머지 정상, 실제 동시 실행 여부(예: `threading.Barrier(2, timeout=5)`로 두 task가 동시에 대기해야만 통과).

## 요구사항 ID

R3

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/runner.py`
- `tests/test_runner.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_runner.py   # runner 테스트 통과 (fake runner만 사용)
py -m pytest -q                        # 전체 통과
py scripts/scope_check.py phases/0-mvp/step3.md   # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
3. 결과에 따라 `phases/0-mvp/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 실제 `claude`를 실행하지 마라(테스트·수동 확인 모두). 이유: 과금 호출, CLAUDE.md CRITICAL.
- `shell=True`나 문자열 명령을 쓰지 마라. 이유: ADR-002, 인자 injection.
- 에이전트 프롬프트·schema를 여기에 넣지 마라. 이유: step 4(`agents.py`)의 책임.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
