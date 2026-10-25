# Step 0: gate-criteria

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-006: 게이트는 workflow 안에서만 막는다 · test·reverify 는 판정하지 않고 게이트가 판정한다 · 분류 기준 목록은 base 판
- ADR-007: 1차 임시 기준(아래 표) — 판정은 코드로(결정적), 판정 불가는 fail-closed, 리뷰 실패는 PASS + `degraded`

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/gate.py` (강제 스위치까지 — 이 step 에서 기준을 더한다)
- `loop/contract.py` (`test`·`reverify`·`review`·`merge`·`gate-*` 키 — `expected_head`, `fixed`, `unexpected`, `missing`, `status`)
- `loop/test_report.py` (분류 정의 ⓐⓑⓒ)
- `loop/run_local.py`, `tests/test_loop_gate_switch.py`, `tests/test_loop_run_local.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

게이트 3개에 **1차 임시 기준**을 넣는다. 강제 스위치(`force-block-<게이트>`)가 있으면 기준보다 먼저 BLOCK 이다(지금 동작 유지).

### 1. `loop/gate.py`
upstream(기존 + 추가): autofix ← `test`, `review` / merge ← `reverify`, `review` / release ← `merge`, `reverify`, `gate-merge`. 없으면 exit 1(fail-closed, 지금과 같음).

| 게이트 | 기준 (위에서부터 처음 맞는 것) | `go` | `decision` |
|---|---|---|---|
| autofix | test `status == "error"` | false | `NEEDS_INVESTIGATION` |
| | `unexpected` 0건 | false | `NO_ACTION` |
| | `unexpected` 1 ~ `AUTOFIX_MAX`(=3)건 | true | `AUTO_FIX` |
| | `unexpected` 4건 이상 | false | `NEEDS_HUMAN` |
| merge | reverify `status == "error"` | false | `BLOCK` (reason 「판정 불가 — reverify error」) |
| | `unexpected` 또는 `missing` 이 비어 있지 않음 | false | `BLOCK` (reason 에 건수와 식별자) |
| | `fixed` 가 비어 있지 않고 그중 하나라도 `expected_head` 에 남아 있음 | false | `BLOCK` (reason 「목록 갱신 필요(사람 몫)」 + 식별자) |
| | 그 밖 | true | `PASS` |
| release | merge `merged` 가 false | false | `BLOCK` |
| | reverify 가 merge 기준을 통과하지 못함(위 merge 행과 같은 판정 함수 재사용) | false | `BLOCK` |
| | 그 밖 | true | `PASS` |

- **degraded**: merge 게이트는 review `status == "error"` 이면 판정은 그대로 두고 `degraded: true` + reason 끝에 「리뷰 실패 — 리뷰 없이 판정」. release 게이트는 `gate-merge.json` 의 `degraded` 를 그대로 옮긴다. 리뷰 critical 은 막지 않는다(정적 추정 — reason 에 건수만 적는다).
- 판정 함수는 순수 함수로 분리한다: `decide_autofix(test: dict) -> tuple[bool, str, str]`, `decide_merge(reverify: dict, review: dict) -> tuple[bool, str, str, bool]`, `decide_release(merge: dict, reverify: dict, gate_merge: dict) -> tuple[bool, str, str, bool]` (go, decision, reason[, degraded]). `AUTOFIX_MAX = 3` 은 모듈 상수.
- exit code 규칙은 지금과 같다: merge · release 는 `go` false 면 exit 1, autofix 는 항상 exit 0.

### 2. `loop/run_local.py`
- fixture 를 하나 더 받을 수 있게: 지금 구조 그대로 두고, fixture 폴더에 `reverify-results/` 가 있으면 reverify 단계는 그 XML 을 쓴다(없으면 `test-results/` 재사용).
- 기대 동작이 workflow 와 같게: autofix `go` false → fix skip, merge exit 1 → merge·release-gate·release skip.

### 3. fixture (`tests/fixtures/loop/`)
- `new-defect/`: basic 의 XML 에서 통과 케이스 1개를 실패로 바꾼 판(+ 같은 `expected-base.txt`·`tests/expected_failures.txt`). reverify 도 같은 XML → AUTO_FIX → fix → merge BLOCK.
- `fixed-unlisted/`: base 목록 케이스 1개가 통과하는 XML, head 목록은 그대로 → merge BLOCK(목록 갱신 필요).
- `fixed-listed/`: 같은 XML, head 목록에서 그 케이스를 지움 → merge PASS.
- `build-broken/`: `test-results/` 에 XML 없음 → test status error → NEEDS_INVESTIGATION, reverify error → merge BLOCK.

### 4. 테스트
- `tests/test_loop_gate_criteria.py`: 판정 함수 표의 각 행(경계값 0 · 1 · 3 · 4 포함) · degraded 전파 · 강제 스위치가 기준보다 먼저.
- `tests/test_loop_run_local.py` 에 추가: 네 fixture 의 기대 흐름(어느 단계까지 가고 무엇이 skip 되는지, release.json 유무).
- 기존 테스트 중 「무게이트(항상 PASS)」를 기대하던 assert 는 이 step 의 의도된 변경이다 — 기준에 맞게 고치고 summary 에 적는다(그 밖의 assert 는 약화하지 않는다).

## 요구사항 ID

R12

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/gate.py`
- `loop/run_local.py`
- `tests/test_loop_gate_criteria.py`
- `tests/test_loop_gate_switch.py`
- `tests/test_loop_run_local.py`
- `tests/test_loop_stages.py`
- `tests/fixtures/loop/*`

## Acceptance Criteria

```bash
py -m pytest -q                                                              # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/basic                     # exit 0 (NO_ACTION → PASS → release)
py -m loop.run_local --fixture tests/fixtures/loop/new-defect                # exit 0 (AUTO_FIX → fix → merge BLOCK, release 없음)
py scripts/scope_check.py phases/3-loop-criteria/step0.md                    # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `AUTOFIX_MAX` 비교를 `<` 로 바꿔(3건이 NEEDS_HUMAN) 경계 테스트가 실패하는지, merge 판정에서 `missing` 검사를 빼고 실패하는지, reverify error 를 PASS 로 바꿔 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/3-loop-criteria/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 실제 `gh`·`git`·`claude`·`make` 를 실행하지 마라. 이유: CLAUDE.md CRITICAL.
- 판정에 LLM 을 쓰지 마라. 이유: ADR-007 — 판정은 결정적 코드.
- 표에 없는 기준(리뷰 critical 로 막기, 파일 경로로 막기 등)을 넣지 마라. 이유: 1차 임시 기준은 실장 결정 대기 — 승인된 표만 구현.
- `loop/templates/pr-loop.yml`·`loop/fix.py` 를 고치지 마라. 이유: 다음 step 몫.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
