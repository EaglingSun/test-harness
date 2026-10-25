# Step 0: gate-switch

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-004: 외부 호출(gh)은 runner 주입 — 테스트는 fake runner
- ADR-006: 게이트는 workflow 안에서만 막는다(merge · release BLOCK = exit 1, autofix 는 exit 0 + `go=false`). 라벨은 실행 시점에 읽는다(이벤트 페이로드 스냅샷 아님)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/gate.py` (1차 무게이트 — 이 step 에서 강제 스위치를 더한다)
- `loop/contract.py` (`gate-*` 계약 키)
- `loop/run_local.py` (FakeRunner · 단계 순서)
- `tests/test_loop_stages.py`, `tests/test_loop_run_local.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**멈추는 장치**를 게이트에 단다. 기준은 여전히 「항상 통과」다 — 라벨로 강제로 멈출 때만 막는다.

### 1. `loop/gate.py`
- 인자 추가: `--repo OWNER/REPO`, `--pr N` (둘 다 필수).
- upstream 계약 확인(기존) 뒤, **실행 시점 라벨**을 읽는다: `gh pr view <N> -R <repo> --json labels,state` → `labels[].name`.
- 라벨 `force-block-<gate>`(예: merge 게이트는 `force-block-merge`)가 있으면: `go: false`, `decision: "BLOCK"`, `forced: true`, `reason: "강제 스위치 force-block-<gate>"`. 다른 게이트의 라벨은 영향이 없다.
- 없으면 지금과 같다: `go: true`, `decision: "PASS"`, `forced: false`, `reason: "무게이트(1차 뼈대)"`.
- 계약 JSON 에 `labels`(읽은 라벨 이름 목록)와 `pr_state`(`state` 값)를 추가 키로 남긴다.
- `gh pr view` 가 실패하거나 JSON 이 깨지면 **fail-closed**: stderr 메시지 + exit 1(계약 파일을 쓰지 않는다). 라벨을 못 읽었는데 통과시키지 않는다.
- exit code 규칙은 지금과 같다: merge · release 는 `go` false 면 exit 1, autofix 는 항상 exit 0. `write_github_output("go", ...)` 는 그대로.

### 2. `loop/run_local.py`
- 인자 추가: `--labels NAME[,NAME...]` (기본 없음). FakeRunner 의 `gh pr view ... --json labels,state` 응답이 이 라벨을 돌려준다.
- 단계 실행을 workflow 와 같게 맞춘다: autofix 게이트가 `go: false` 면 fix 를 건너뛰고 reverify 로 간다. merge 게이트가 exit 1 이면 merge · release-gate · release 를 건너뛴다. release 게이트가 exit 1 이면 release 를 건너뛴다.
- 건너뛴 단계는 요약에 `skipped` 로 찍는다. 실행한 단계가 모두 계약대로 끝나면 exit 0 — 라벨이 없을 때는 지금처럼 `release.json` 까지 있어야 exit 0.

### 3. 테스트 (fake runner · 실제 gh 실행 금지)
- `tests/test_loop_gate_switch.py`:
  - 게이트 3종 × (라벨 없음 → PASS · 자기 라벨 → BLOCK/forced · 다른 게이트 라벨만 → PASS).
  - merge · release BLOCK → exit 1, autofix BLOCK → exit 0 + `GITHUB_OUTPUT` 에 `go=false`.
  - `gh pr view` 실패 → exit 1, 계약 파일 없음.
  - 계약에 `labels` · `pr_state` 가 남는다.
  - `gh pr view` 인자가 `["gh", "pr", "view", "<N>", "-R", "<repo>", "--json", "labels,state"]` 형태다.
- `tests/test_loop_run_local.py` 에 추가: `--labels force-block-autofix` → fix skipped · release.json 있음 / `force-block-merge` → merge · release skipped · release.json 없음 · exit 0 / `force-block-release` → merge 됨 · release skipped.
- 기존 `tests/test_loop_stages.py` 의 gate 테스트가 새 필수 인자 때문에 깨지면 인자만 넣어 고친다(assert 는 약화하지 않는다).

## 요구사항 ID

R11

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/gate.py`
- `loop/run_local.py`
- `tests/test_loop_gate_switch.py`
- `tests/test_loop_run_local.py`
- `tests/test_loop_stages.py`

## Acceptance Criteria

```bash
py -m pytest -q                                                                   # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/basic                          # exit 0 (release 까지)
py -m loop.run_local --fixture tests/fixtures/loop/basic --labels force-block-merge   # exit 0 (merge·release skipped)
py scripts/scope_check.py phases/2-loop-stop/step0.md                             # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `gh pr view` 실패 시 PASS 로 통과시키도록 일부러 바꿔 테스트가 실패하는지 확인한 뒤 되돌린다. 라벨 이름 비교를 `force-block-` 접두사만 보도록 일부러 바꿔(다른 게이트 라벨에도 막힘) 테스트가 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
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

- 실제 `gh` 를 실행하지 마라. 이유: 실제 저장소 상태 조회·변경 방지(CLAUDE.md CRITICAL).
- 테스트 결과·리뷰 결과로 막는 기준을 넣지 마라. 이유: 기준은 다음 phase 몫 — 이 step 은 강제 스위치만.
- 이벤트 페이로드(`GITHUB_EVENT_PATH`)의 라벨을 판정에 쓰지 마라. 이유: PR 생성 직후 붙인 라벨이 opened 페이로드에 없을 수 있다.
- `loop/templates/pr-loop.yml` 을 고치지 마라. 이유: 다음 step 몫.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
