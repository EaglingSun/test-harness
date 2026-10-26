# Step 0: review-critical-needs-human

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-007: 판정은 결정적 코드(`loop/gate.py` 순수 함수). merge 게이트 — 리뷰 critical(게시 기준)이 있으면 NEEDS_HUMAN, 라벨 `review-accepted` 가 있으면 막지 않음(2026-10-26 실장 결정 · R15)
- ADR-006: 게이트는 workflow 안에서만 막는다 · 강제 스위치 라벨은 실행 시점 PR 라벨로 읽는다

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/gate.py` (`decide_merge` · `decide` · `main` 의 라벨 읽기)
- `loop/review.py` (`_real` · `_stub`)
- `loop/contract.py` (review 필수 키)
- `pr_reviewer/aggregate.py` (`build_review_plan` — 강등 뒤 critical 이 있으면 `REQUEST_CHANGES`, 자기 PR 이면 `COMMENT` + 요약에 `OWN_PR_CRITICAL`)
- `loop/templates/pr-loop.yml` (labeled 트리거 조건 · concurrency group)
- `tests/test_loop_gate_criteria.py` · `tests/test_loop_review.py` · `tests/test_loop_workflow.py` · `tests/test_loop_contract.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

실장 결정(2026-10-26): 리뷰 critical 이 있으면 merge 게이트가 사람 확인(NEEDS_HUMAN)으로 막는다. 푸는 방법은 PR 라벨 `review-accepted`. critical 은 **게시 기준**(ADR-005 강등 뒤 — 게시된 리뷰가 실제로 critical 을 말한 경우)으로 센다. 지금 계약의 `counts` 는 원천 등급(`counts_basis: agent_raw`)이라 쓰지 않는다.

### `loop/review.py`
- review 계약에 `critical_posted`(bool)를 더한다.
  - real: plan 의 `event == "REQUEST_CHANGES"` 이거나 `summary_markdown` 에 `pr_reviewer.aggregate.OWN_PR_CRITICAL` 문구가 있으면 True. plan 이 없으면 False.
  - stub: False.
- `counts` · `counts_basis` 는 그대로 둔다.

### `loop/contract.py`
- review 필수 키에 `critical_posted` 를 더하고 bool 타입 검사에 넣는다(기존 bool 키 검사 방식을 따른다).

### `loop/gate.py`
- 라벨 상수 `REVIEW_ACCEPTED = "review-accepted"`.
- `decide_merge(reverify, review, accepted=False)`:
  1. reverify 판정이 go False 면 지금처럼 BLOCK(그 사유가 먼저).
  2. 그렇지 않고 `review["critical_posted"]` 가 True 이고 `accepted` 가 False 면 → `(False, "NEEDS_HUMAN", "리뷰 critical — 사람 확인 필요(라벨 review-accepted)", degraded)`.
  3. `critical_posted` True 이고 `accepted` True 면 → PASS · reason 끝에 ` · 리뷰 critical — review-accepted 로 사람 확인됨`.
  4. degraded · 부분 실패 표시는 지금 그대로.
- 원천 `counts` critical 표시 문구(「정적 추정 — 막지 않음」)는 지운다(판정 근거가 바뀌었으므로).
- `decide(name, up, labels=())` 로 라벨을 받아 merge 일 때만 `accepted = REVIEW_ACCEPTED in labels` 를 넘긴다. `main` 은 이미 읽은 `labels` 를 넘긴다. 강제 스위치가 먼저인 순서는 그대로.
- merge 게이트가 NEEDS_HUMAN 이면 go False 이므로 exit 1(빨간 체크) — 지금 BLOCK 과 같다.

### `loop/templates/pr-loop.yml`
- labeled 이벤트는 `force-block-` 라벨 **또는** `review-accepted` 라벨일 때만 루프를 돈다(start job `if` · concurrency group 의 skip 조건 둘 다).
- 머리 주석 설치 4번에 `gh label create review-accepted` 를 더한다.

### 테스트
- `tests/test_loop_gate_criteria.py`
  - 헬퍼 `review()` 에 `critical_posted=False` 인자를 더한다(기존 호출 호환).
  - critical_posted True · accepted False → (False, "NEEDS_HUMAN").
  - critical_posted True · accepted True → (True, "PASS") · reason 에 「review-accepted」.
  - critical_posted True + reverify unexpected → BLOCK(reverify 가 먼저).
  - 원천 counts critical 2 · critical_posted False → PASS(기존 `test_merge_review_critical_does_not_block` 을 이 뜻으로 고친다 — assert 를 약화하지 말고 판정 근거가 바뀐 것을 반영).
  - `main` merge: 라벨에 `review-accepted` 가 있으면 PASS · exit 0 / 없으면 NEEDS_HUMAN · exit 1.
- `tests/test_loop_review.py`: real — event REQUEST_CHANGES → True · COMMENT + OWN_PR_CRITICAL 문구 → True · COMMENT 만 → False · plan 없음 → False. stub → False.
- `tests/test_loop_workflow.py`: labeled 조건과 concurrency group 이 `review-accepted` 를 포함한다.
- `tests/test_loop_contract.py`: review 계약에 `critical_posted` 가 없으면 read 가 거부한다.

## 요구사항 ID

R15

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/gate.py`
- `loop/review.py`
- `loop/contract.py`
- `loop/templates/pr-loop.yml`
- `tests/test_loop_gate_criteria.py`
- `tests/test_loop_review.py`
- `tests/test_loop_workflow.py`
- `tests/test_loop_contract.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_gate_criteria.py tests/test_loop_review.py tests/test_loop_workflow.py tests/test_loop_contract.py   # 통과
py -m pytest -q                                                            # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/basic                   # 한 바퀴 — merge PASS(stub 은 critical_posted False)
py scripts/scope_check.py phases/7-loop-review-critical/step0.md           # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 고치기 **전** 코드에서 새 테스트가 실패하는 것을 먼저 확인(RED)하고, 고친 뒤 통과(GREEN), `decide_merge` 의 critical_posted 검사 한 줄만 지워 다시 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가? (테스트에서 실제 gh/claude 를 실행하지 않는다)
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/7-loop-review-critical/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- release 게이트(`decide_release`)를 바꾸지 마라. 이유: 머지 뒤에는 리뷰를 보지 않는다(실장 확인 2026-10-26).
- autofix 게이트 기준(`AUTOFIX_MAX` · 4상태)을 바꾸지 마라. 이유: 이 step 범위 밖이다.
- `pr_reviewer/` 를 고치지 마라. 이유: 게시 기준 critical 은 plan 의 event · 요약 문구로 이미 알 수 있다.
- 원천 `counts` · `counts_basis` 를 바꾸지 마라(P13 은 별도 제안).
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
