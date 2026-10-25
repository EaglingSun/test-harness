# Step 0: gate-evidence-upload

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-006: 게이트 BLOCK = exit 1 → 다음 동작 job skip · test·reverify 는 판정하지 않는다(판정 불가도 게이트가 판정)
- ADR-007: 판정 불가 → autofix NEEDS_INVESTIGATION · merge BLOCK(fail-closed)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/templates/pr-loop.yml`
- `tests/test_loop_workflow.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**E2E 에서 드러난 결함 2건**을 workflow 틀에서 고친다(2026-10-25 리허설 저장소).

1. **빌드가 깨지면 test job 이 실패해 게이트가 판정 불가를 판정하지 못한다** (PR #10, run 40202995243): `loop-junit` upload 가 `if-no-files-found: error` 라 XML 이 없으면 job 이 실패하고 뒤 job 이 전부 skip 됐다. `loop-test` 계약에는 이미 `status: "error"` 가 들어 있었다.
   - 수정: `loop-junit` upload 만 `if-no-files-found: warn`. (계약 JSON upload 들은 `error` 유지 — 계약 파일이 없으면 실패가 맞다.)
2. **게이트가 BLOCK(exit 1)이면 그 job 의 계약 JSON 이 artifact 로 남지 않는다** (PR #6, run 40202825571 — `loop-gate-merge` 없음): 게이트 step 이 실패하면 뒤 upload step 이 기본 조건으로 건너뛰어진다. BLOCK 의 근거(reason)가 증거로 남지 않는다.
   - 수정: 게이트 job 3개의 upload step 에 `if: ${{ !cancelled() }}`. 게이트 step 은 그대로 exit 1(빨간 체크 유지).

### `tests/test_loop_workflow.py`
- `loop-junit` upload 의 `if-no-files-found == "warn"`, 그 밖 `loop-*` 계약 upload 는 `error`.
- 게이트 job(autofix-gate · merge-gate · release-gate)의 upload step 에 `!cancelled()` 조건.
- 위 두 검사 위 주석에 E2E 근거(PR #10 · PR #6)를 적는다.

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
py scripts/scope_check.py phases/5-loop-evidence/step0.md    # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 고치기 **전** 템플릿에서 새 검사가 실패하는 것을 먼저 확인(RED)하고, 고친 뒤 통과(GREEN), merge-gate upload 의 `if` 하나만 지워 다시 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/5-loop-evidence/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 게이트 step 의 exit 1 을 없애거나 `continue-on-error` 를 달지 마라. 이유: BLOCK 은 빨간 체크로 보여야 한다(ADR-006).
- `if: always()` 를 쓰지 마라. 이유: 취소된 run 에서도 upload 가 돈다.
- `loop/*.py` 를 고치지 마라. 이유: 이 step 은 workflow 결함만.
- 템플릿을 vsm 저장소에 복사하거나 push 하지 마라.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
