# Step 0: review-partial-degraded

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-007: 판정은 결정적 코드(`loop/gate.py` 순수 함수) · 리뷰 실패는 PASS + `degraded: true`(release까지 전파) · 리뷰 부분 실패도 degraded(2026-10-26 추가)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/gate.py`
- `loop/review.py` (`_real` — 에이전트 `error` 가 `errors[]` 로 모인다)
- `tests/test_loop_gate_criteria.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**E2E 에서 드러난 결함 D4** (2026-10-25 리허설 저장소 PR #6): real 리뷰 에이전트 3개 중 1개가 `permission denied: Bash` 로 실패했지만 리뷰는 게시됐고 `review.json` 은 `status: "ok"` + `errors` 1건이었다. merge 게이트는 `status == "error"` 일 때만 degraded 로 표시하므로 부분 실패가 판정 근거에 드러나지 않았다. 실장 결정(§8 #4): 부분 실패는 degraded 로 표시한다.

### `loop/gate.py` — `decide_merge`
- `review["status"] == "error"` 이면 지금처럼 degraded + `DEGRADED_NOTE`.
- 그렇지 않고 `review["errors"]` 가 1건 이상이면 degraded = True, reason 끝에 ` · 리뷰 부분 실패 {n}건` 을 붙인다(문구는 상수로 둔다).
- **판정(go · decision)은 바꾸지 않는다.** degraded 는 표시만 한다.
- release 로 전파하는 `decide_release` 는 그대로(gate-merge 의 degraded 를 옮긴다).

### `tests/test_loop_gate_criteria.py`
- 부분 실패(`status ok` + `errors` 1건) → (True, "PASS", degraded True) · reason 에 「리뷰 부분 실패 1건」.
- 부분 실패 + reverify ⓐ → (False, "BLOCK", True).
- 전원 성공(`errors` 빈 목록) → degraded False(기존 테스트가 이미 다루면 그대로 둔다).
- 테스트 헬퍼 `review()` 에 `errors` 인자를 기본값 빈 목록으로 더한다(기존 호출 호환).

## 요구사항 ID

R14

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/gate.py`
- `tests/test_loop_gate_criteria.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_gate_criteria.py              # 통과
py -m pytest -q                                               # 전체 통과
py scripts/scope_check.py phases/6-loop-degraded/step0.md     # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 고치기 **전** 코드에서 새 테스트가 실패하는 것을 먼저 확인(RED)하고, 고친 뒤 통과(GREEN), `errors` 검사 한 줄만 지워 다시 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/6-loop-degraded/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 부분 실패로 BLOCK 하지 마라. 이유: 실장 결정은 「표시」이고 판정은 그대로다(§8 #4).
- review 계약의 status 값(ok/error)이나 `loop/contract.py` 를 바꾸지 마라. 이유: 계약 변경은 이 step 범위 밖이다.
- `loop/review.py` 를 고치지 마라. 이유: `errors` 는 이미 계약에 들어 있다.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
