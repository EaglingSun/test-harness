# Step 7: severity-fix

## 참조 문서

- `docs/ADR.md`

## 근거 ADR

- ADR-005: 에이전트 A(실행 근거) — 변경 라인에 매핑된 테스트 실패 = critical, 변경 라인 매핑 근거가 없는 실패 = 인라인 없이 요약에 major

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `pr_reviewer/aggregate.py` (`apply_severity_rules`, `build_review_plan`)
- `tests/test_aggregate.py`
- `pr_reviewer/models.py` (Finding, ReviewPlan)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

`/review`에서 발견한 결함을 고친다. 순서: 재현 테스트 → 수정 → 통과.

**결함**: `structural_test` finding이 `line`을 갖고 있지만 그 line이 diff의 commentable line이 아니면(변경되지 않은 코드), 현재는 `critical`로 남은 채 요약 전용이 된다. 이 critical이 review event를 `REQUEST_CHANGES`로 만든다.
재현: `Finding('structural_test','src/a.py',99,...)`, `commentable={'src/a.py':{10,11}}`, 작성자≠현재 사용자 → `event == "REQUEST_CHANGES"`, 요약에 `(critical) ... (요약 전용)`.
ADR-005에 따르면 이 경우는 "변경 라인 매핑 근거가 없는 실패"이므로 요약 전용 `major`여야 한다.

수정 규칙:
- `build_review_plan`에서 요약 전용으로 분류되는 `structural_test` finding의 severity를 `major`로 바꾼다. 인라인 대상이 되는 `structural_test` finding은 `critical`을 유지한다.
- review event 판정과 요약의 등급별 개수 표는 **이 조정 이후의** severity를 기준으로 한다.
- `apply_severity_rules`의 기존 시그니처와 동작(순수 함수, line 유무 기준)은 바꾸지 마라. 이유: 기존 테스트와 계약 유지. 조정은 commentable 정보를 아는 `build_review_plan`에서 한다.
- `security`/`code_review` finding의 등급 규칙은 바꾸지 마라.

### `tests/test_aggregate.py`에 회귀 테스트 추가
- A finding이 diff 밖 line을 지목 → 요약 전용, 요약에 `(major)`로 표시, 다른 critical이 없으면 `event == "COMMENT"`.
- A finding이 diff 안 line을 지목 → 인라인, `critical`, 타인 PR이면 `REQUEST_CHANGES` (기존 동작 유지 확인).
- A finding이 diff에 없는 파일을 지목 → 요약 전용 `major`.
- 등급별 개수 표가 조정 후 등급(Major)으로 집계됨.

## 요구사항 ID

R4

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/aggregate.py`
- `tests/test_aggregate.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_aggregate.py   # 회귀 테스트 포함 통과
py -m pytest -q                           # 전체 통과
py scripts/scope_check.py phases/0-mvp/step7.md   # 범위 이탈 없음
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

- 기존 테스트의 assert를 삭제하거나 기대값을 바꿔 통과시키지 마라. 이유: 테스트 약화 금지. 기존 테스트가 이 결함 동작(diff 밖 A finding = critical)을 기대하고 있다면 그 테스트만 ADR-005에 맞게 고치고, 결과 보고 summary에 그 사실을 적어라.
- ADR-005에 없는 등급 규칙을 추가하지 마라. 이유: 승인된 정책만 구현.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
