# Step 1: workflow-labels

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-006: 한 workflow job 체인 · 게이트는 workflow 안에서만 막는다 · GITHUB_TOKEN 만

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/templates/pr-loop.yml`
- `tests/test_loop_workflow.py`
- `loop/gate.py` (step 0 — 새 필수 인자 `--repo`, `--pr`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### 1. `loop/templates/pr-loop.yml`
- 트리거 `types` 에 `labeled` 추가: `[opened, synchronize, reopened, labeled]`. 주석의 「다음 phase 에서 labeled 를 추가할 자리」 문구를 지우고, 왜 넣는지(강제 스위치 라벨을 붙이면 루프를 다시 돌려 막는다) 한 줄로 바꾼다.
- 첫 job `test` 에 `if: ${{ github.event.action != 'labeled' || startsWith(github.event.label.name, 'force-block-') }}` — `force-block-` 이 아닌 라벨은 루프를 돌리지 않는다(뒤 job 은 needs 로 연쇄 skip).
- concurrency group 을 `pr-loop-${{ github.event.pull_request.number }}${{ (github.event.action == 'labeled' && !startsWith(github.event.label.name, 'force-block-')) && format('-skip-{0}', github.run_id) || '' }}` 로 바꾼다. 이유: concurrency 는 pending run 을 1건만 남겨 새 pending 이 옛 pending 을 취소한다 — 아무 라벨이나 붙인 run 이 진짜 run 을 밀어내지 않게 따로 둔다.
- 게이트 step 3개(autofix · merge · release)에 `--repo ${{ github.repository }} --pr ${{ github.event.pull_request.number }}` 를 넘긴다.
- 머리 주석 설치 절차에 「라벨 3개 생성: `gh label create force-block-autofix` · `force-block-merge` · `force-block-release`」 를 추가한다.

### 2. `tests/test_loop_workflow.py`
- types 기대값을 `["opened", "synchronize", "reopened", "labeled"]` 로 바꾼다.
- 추가 검사: `test.if` 에 `github.event.action != 'labeled'` 와 `startsWith(github.event.label.name, 'force-block-')` · concurrency group 에 `github.run_id` 와 `force-block-` · 게이트 step 3개가 `--repo` · `--pr` 를 넘긴다 · 머리 주석에 라벨 3개 이름이 있다.

## 요구사항 ID

R11

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/templates/pr-loop.yml`
- `tests/test_loop_workflow.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_workflow.py                  # 구조 테스트 통과
py -m pytest -q                                              # 전체 통과
py scripts/scope_check.py phases/2-loop-stop/step1.md        # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `test.if` 를 지우고 테스트가 실패하는지, 게이트 step 하나에서 `--pr` 를 지우고 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/2-loop-stop/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 템플릿을 vsm 저장소에 복사하거나 GitHub 에 push 하지 마라. 이유: 설치는 phase 완료 후 메인 세션 E2E 몫.
- `secrets`·PAT·`workflow_dispatch` 를 넣지 마라. 이유: ADR-006.
- `loop/*.py` 를 수정하지 마라. 이유: 이 step 범위 밖.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라(types 기대값 변경은 이 step 의 의도된 변경이다 — summary 에 적어라).
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
