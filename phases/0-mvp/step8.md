# Step 8: structural-prompt-fix

## 참조 문서

- `docs/ADR.md`

## 근거 ADR

- ADR-002: 에이전트 A는 `claude -p --json-schema`, 프롬프트는 stdin
- ADR-005: 에이전트 A — 변경 라인에 매핑된 테스트 실패 = critical, 변경 라인 매핑 근거가 없는 실패 = 요약에 major

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `pr_reviewer/agents.py` (`review_structural_tests`의 프롬프트, `LOCATION_RULES`)
- `tests/test_agents.py`
- `pr_reviewer/aggregate.py` (structural_test finding의 line 유무와 commentable 여부로 critical/major가 갈린다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

E2E(2026-10-25, 실제 PR dry-run)에서 발견한 결함을 고친다.

**결함**: 테스트를 추가하는 PR에서 기존 코드(`src/`, diff 밖)의 버그로 테스트가 실패했다. 에이전트 A는 본문에 "PR 변경분에 결함은 없다. 원인은 diff 밖의 src/..."라고 쓰면서도, `path`/`line`에는 PR이 추가한 **테스트 파일의 assert 줄**(예: `tests/test_speed_monitor.c:43`)을 적었다. 그 줄은 diff 안이므로 aggregate가 "변경 라인에 매핑된 실패"로 보고 critical 8건이 되었다. ADR-005의 의도는 "원인이 된 변경 코드"에 매핑된 실패만 critical이다.

수정: `review_structural_tests` 프롬프트의 지시에 아래 규칙을 명시적으로 추가한다(문구는 재량, 의미는 유지).
1. `path`/`line`은 실패의 **원인이 된 제품 코드** 위치다. 실패를 검출한 테스트 코드(assert/expect 줄, 테스트 파일)의 위치를 적지 마라.
2. 원인 코드가 diff 밖이거나(이 PR이 바꾸지 않은 코드) 특정할 수 없으면 `line`을 `null`로 둔다. 이 경우 `path`에는 원인으로 추정되는 파일 경로를 적되, 모르면 실패한 테스트 파일 경로를 적는다.
3. 단, 테스트 코드 자체가 이 PR에서 잘못 작성되어 실패한 경우(기대값 오류 등)에는 그 테스트 줄이 원인 코드이므로 line을 적는다. body에 그 판단 근거를 적는다.

`LOCATION_RULES`(B/C 공용)는 바꾸지 마라. 이유: B/C에는 해당하지 않는 규칙이며 범위 밖 변경이다. A 전용 지시에만 추가한다.

### `tests/test_agents.py`에 테스트 추가
- fake runner가 받은 A의 stdin 프롬프트에 위 1~3 규칙의 핵심 문구(예: "원인이 된 제품 코드", "테스트 코드 … 위치를 적지 마라", "diff 밖 … null")가 포함되어 있는지 검사한다.
- B 프롬프트에는 이 A 전용 문구가 없는지 검사한다(관점 분리).

## 요구사항 ID

R3

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/agents.py`
- `tests/test_agents.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_agents.py   # 프롬프트 규칙 테스트 포함 통과
py -m pytest -q                        # 전체 통과
py scripts/scope_check.py phases/0-mvp/step8.md   # 범위 이탈 없음
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

- 실제 `claude`를 실행해 프롬프트를 시험하지 마라. 이유: 과금 호출, CLAUDE.md CRITICAL. 효과는 phase 완료 후 메인 세션의 E2E dry-run으로 확인한다.
- `aggregate.py`에 "테스트 파일 경로면 critical 금지" 같은 코드 규칙을 넣지 마라. 이유: ADR-005에 없는 새 정책이며 이 step의 범위 밖이다.
- 기존 테스트의 assert를 삭제하거나 약화하지 마라.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
