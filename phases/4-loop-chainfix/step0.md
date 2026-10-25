# Step 0: skip-chain-fix

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-006: 한 workflow job 체인 · autofix 게이트가 `go=false` 면 fix 만 건너뛰고 나머지는 돈다
- ADR-007: autofix NO_ACTION / NEEDS_HUMAN / NEEDS_INVESTIGATION 이어도 merge 게이트가 판정한다

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/templates/pr-loop.yml` (job 체인 · 지금 `if:` 는 test · fix · reverify 에만 있다)
- `tests/test_loop_workflow.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**E2E 에서 드러난 연결 결함**을 고친다(2026-10-25 리허설 저장소 PR #3, run 40201593699).

**결함**: autofix 게이트가 `go=false`(라벨 `force-block-autofix` 또는 NO_ACTION 등)면 fix 가 skip 된다. reverify 는 명시적 `if` 로 돌지만, 그 뒤 `merge-gate` · `merge` · `release-gate` · `release` 는 `if` 가 없어 **전부 skip** 됐다. GitHub Actions 의 job 기본 조건 `success()` 는 직접 needs 만이 아니라 **조상 job 중 하나라도 skip/실패면 거짓**이라, fix 의 후손 job 은 모두 명시적 조건이 있어야 돈다. 결과: 문서만 바꾼 PR(NO_ACTION)이 머지에 영영 도달하지 못한다.

### 1. `loop/templates/pr-loop.yml`
- `merge-gate`: `if: ${{ !cancelled() && needs.reverify.result == 'success' }}`
- `merge`: `if: ${{ !cancelled() && needs.merge-gate.result == 'success' }}`
- `release-gate`: `if: ${{ !cancelled() && needs.merge.result == 'success' }}`
- `release`: `if: ${{ !cancelled() && needs.release-gate.result == 'success' }}`
- 네 job 위에 왜 필요한지 주석 한 줄(「fix 가 skip 되면 조상에 skip 이 생겨 기본 조건이 거짓 — 명시적 if 필요」).
- 게이트가 BLOCK(exit 1)이면 그 job 의 result 가 `failure` 라 다음 동작 job 은 여전히 돌지 않는다 — 막는 동작은 그대로다.

### 2. `tests/test_loop_workflow.py`
- needs 그래프에서 `fix` 의 모든 후손 job(reverify · merge-gate · merge · release-gate · release)을 코드로 구한 뒤, 각 job 의 `if` 에 `!cancelled()` 가 있고, reverify 를 뺀 나머지는 `needs.<직접 needs 한 job>.result == 'success'` 가 있는지 검사한다. 후손 목록을 하드코딩하지 말고 needs 에서 계산한다(job 이 늘어도 잡히게).
- 테스트 위 주석에 GitHub 규칙(조상 skip 전파)과 이 결함의 E2E 근거(PR #3)를 적는다.

## 요구사항 ID

R8

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/templates/pr-loop.yml`
- `tests/test_loop_workflow.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_workflow.py                  # 통과
py -m pytest -q                                              # 전체 통과
py scripts/scope_check.py phases/4-loop-chainfix/step0.md    # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 고치기 **전** 템플릿(지금 상태)에서 새 테스트가 실패하는 것을 먼저 확인하고(RED), 고친 뒤 통과(GREEN), 이어서 `merge` 의 `if` 하나만 지워 다시 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/4-loop-chainfix/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- `if: always()` 를 쓰지 마라. 이유: 취소된 run 에서도 머지·릴리스가 돌 수 있다(`!cancelled()` + 직접 needs 결과로 제한).
- 게이트 기준·`loop/*.py` 를 고치지 마라. 이유: 이 step 은 workflow 연결 결함만.
- 템플릿을 vsm 저장소에 복사하거나 push 하지 마라. 이유: 설치는 메인 세션 E2E 몫.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
