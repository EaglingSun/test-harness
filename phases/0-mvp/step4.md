# Step 4: review-agents

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-002: 에이전트 A/B는 `--json-schema`, C는 `/code-review` 텍스트 → JSON 변환 2단계, 허용/금지 도구
- ADR-005: 심각도 정의, failure_scenario / reachability 근거 필드

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `docs/PRD.md` ("리뷰 에이전트" 표)
- `pr_reviewer/models.py` (Finding, AgentResult, TestReport, PullRequest, CATEGORY_LABELS)
- `pr_reviewer/runner.py` (run_claude, run_parallel, ClaudeError)
- `tests/test_runner.py` (fake runner 패턴)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/agents.py`

```python
FINDINGS_SCHEMA: dict
# {"type":"object","required":["findings"],"properties":{"findings":{"type":"array","items":{
#   "type":"object",
#   "required":["category","path","line","severity","title","body","failure_scenario","reachability"],
#   "properties":{"category":{"enum":["structural_test","security","code_review"]},
#                 "path":{"type":"string"},"line":{"type":["integer","null"]},
#                 "severity":{"enum":["critical","major","minor"]},
#                 "title":{"type":"string"},"body":{"type":"string"},
#                 "failure_scenario":{"type":"string"},"reachability":{"type":"string"}}}}}}

def review_structural_tests(pr: PullRequest, diff: str, report: TestReport | None,
                            runner: Runner = run_process) -> AgentResult: ...
def review_security(pr: PullRequest, diff: str, runner: Runner = run_process) -> AgentResult: ...
def review_code(pr: PullRequest, runner: Runner = run_process) -> AgentResult: ...
def run_all_agents(pr: PullRequest, diff: str, report: TestReport | None,
                   runner: Runner = run_process) -> list[AgentResult]:
    """run_parallel({"structural_test":..., "security":..., "code_review":...}) 결과를 반환."""
```

에이전트별 규칙:

**A `review_structural_tests` (category `structural_test`)**
- `report is None` → `AgentResult(skipped_reason="테스트 결과 없음")`, claude 호출 금지.
- `report.failures`가 비어 있으면 → `skipped_reason="실패 테스트 0건 (총 N건)"`, claude 호출 금지. 이유: 비용 절감(R3).
- 프롬프트(stdin): diff + 실패 테스트 목록(name, classname, kind, message, details, file, line). 지시 내용:
  - 각 실패의 원인이 된 **변경 코드** 위치(path는 diff의 새 경로, line은 새 파일 줄 번호)를 찾아라. 근거가 없으면 `line: null`로 둔다.
  - 관점은 로직 오류, 예외 처리 누락, 경계값, 동등분할이다. 이 실패들 외의 문제는 보고하지 마라.
  - `failure_scenario`에는 테스트 이름과 실패 메시지를 적어라.
- `disallowed_tools=["Bash","Edit","Write"]`.

**B `review_security` (category `security`)**
- 프롬프트(stdin): diff + 보안 관점만(injection, 인증·인가 누락, 시크릿 노출, 안전하지 않은 입력 처리). "보안 외 문제는 보고하지 마라"를 명시한다.
- ADR-005 등급 정의와 근거 규칙(critical/major는 failure_scenario 필수, critical은 reachability 필수)을 프롬프트에 그대로 적는다.
- `disallowed_tools=["Bash","Edit","Write"]`.

**C `review_code` (category `code_review`) — 2단계**
1. `run_claude(None, args_prompt=f"/code-review low {pr.url}", allowed_tools=["Bash(gh pr diff:*)", "Bash(gh pr view:*)"], disallowed_tools=["Edit","Write"])` → 텍스트.
   - `gh api`를 allowed_tools에 넣지 마라. 이유: POST로 GitHub에 게시할 수 있다.
   - `--comment`, `--fix` 플래그를 넣지 마라. 이유: 스킬이 직접 게시·수정하면 취합 단계를 건너뛴다.
   - 이 단계는 prompt(stdin)가 None이다. run_claude가 None을 허용해야 한다(step 3 시그니처).
2. `run_claude(<변환 프롬프트>, schema=FINDINGS_SCHEMA, disallowed_tools=["Bash","Edit","Write"])`. 변환 프롬프트는 1단계 텍스트를 findings로 옮기라고 지시한다. 지시 내용:
   - category는 `code_review`로 둔다.
   - **보안 관련 지적은 제외한다.** 이유: B와 관점 분리.
   - 새 지적을 만들지 마라.
   - ADR-005 등급 정의를 적용한다.
   - 1단계 결과가 "(none)"처럼 지적이 없으면 빈 findings를 반환한다.

공통 규칙:
- structured_output의 각 item을 `Finding`으로 변환한다. **에이전트 자신의 category와 다른 item은 버린다.** 이유: 모델이 관점 지시를 어겨도 범위를 코드로 강제한다.
- 필수 필드 누락이나 타입 오류 item은 버린다. 전체를 실패시키지 마라.
- `ClaudeError`는 잡지 말고 위로 올린다. `run_parallel`이 `AgentResult.error`로 바꾼다.
- 심각도 강등과 병합은 여기서 하지 마라. 이유: aggregate(step 5)의 책임이다.

### `tests/test_agents.py`
- fake runner로만 테스트한다. 명령 args로 어느 에이전트·어느 단계인지 판별해 고정 JSON을 반환한다.
- 최소 케이스:
  - A: report None / 실패 0건이면 runner가 호출되지 않음, 프롬프트에 실패 메시지 포함
  - B: 프롬프트에 diff 포함, disallowedTools 확인
  - C: 1단계 args에 `/code-review low <url>`과 allowedTools 포함·`gh api` 미포함, 2단계 stdin에 1단계 텍스트 포함
  - 다른 category item은 버려짐(예: B 결과에 `code_review` item 섞기)
  - 깨진 item은 버려짐
  - `run_all_agents`에서 C가 ClaudeError → C만 error, A/B 정상

## 요구사항 ID

R3

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/agents.py`
- `tests/test_agents.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_agents.py   # 에이전트 테스트 통과 (fake runner만 사용)
py -m pytest -q                        # 전체 통과
py scripts/scope_check.py phases/0-mvp/step4.md   # 범위 이탈 없음
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

- 실제 `claude`를 실행해 프롬프트를 시험하지 마라. 이유: 과금 호출, CLAUDE.md CRITICAL. 프롬프트 품질은 phase 완료 후 E2E에서 확인한다.
- `/security-review` 스킬을 쓰지 마라. 이유: headless에서 출력이 없다(ADR-002 스파이크 결과).
- `runner.py`를 수정해야 할 것 같으면 수정하지 말고 blocked 처리하라. 이유: 범위 밖이며 step 3의 계약이다.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
