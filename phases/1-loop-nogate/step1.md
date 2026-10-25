# Step 1: workflow-template

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-006: 한 workflow 안 job 체인 · self-hosted(`vsm-loop`) · `working-directory: ${{ vars.LOOP_HOME }}` · artifact `loop-<단계>` · GITHUB_TOKEN 만 · workflow 구조 테스트는 PyYAML(테스트에서만)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/` 전부 (step 0 산출물 — 각 단계의 CLI 인자)
- `loop/run_local.py` (단계 호출 순서)
- `C:\lab\2nd_NGV\vsm_test\.github\workflows\test.yml` (읽기 전용 — 고정 SHA · gcc 캐시 · `make.cmd test` 선례)
- `C:\lab\2nd_NGV\vsm_test\tests\test_ci_workflow.py` (읽기 전용 — yaml 구조 테스트 선례, PyYAML 이 `on:` 을 `True` 키로 읽는 점)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### 1. `loop/templates/pr-loop.yml` (강사 키트 workflow 틀 — vsm 저장소 `.github/workflows/` 에 복사해 쓴다)

머리 주석에 설치 방법(복사 위치 · 저장소 변수 `LOOP_HOME`(runner PC 의 test_harness 경로) · `LOOP_REVIEW_MODE`(기본 stub) · runner 라벨 `vsm-loop`)을 적는다.

```yaml
name: pr-loop
on:
  pull_request:
    branches: [master]
    types: [opened, synchronize, reopened]   # 다음 phase 에서 labeled 를 추가할 자리 — 주석으로 표시
permissions:
  contents: write
  pull-requests: write
concurrency:
  group: pr-loop-${{ github.event.pull_request.number }}
  cancel-in-progress: false
env:
  GH_TOKEN: ${{ github.token }}
  PYTHONUTF8: "1"
```

job 9개(이 이름 그대로) — 모두 `runs-on: [self-hosted, vsm-loop]`, `timeout-minutes: 30`:

| job | needs | if | 하는 일 |
|---|---|---|---|
| `test` | — | — | checkout → gcc 확인 → make(`continue-on-error: true`, `id: make`) → `py -m loop.test_report --stage test --make-outcome ${{ steps.make.outcome }} --base-ref origin/${{ github.base_ref }}` → upload `loop-test`(out/test.json) + `loop-junit`(test-results/*.xml) |
| `review` | test | — | checkout → download → `py -m loop.review --mode ${{ vars.LOOP_REVIEW_MODE \|\| 'stub' }} --repo ${{ github.repository }} --pr ${{ github.event.pull_request.number }}` → upload `loop-review` |
| `autofix-gate` | test, review | — | checkout → download → `py -m loop.gate --gate autofix`(`id: gate`) → upload `loop-gate-autofix`. job `outputs: go: ${{ steps.gate.outputs.go }}` |
| `fix` | autofix-gate | `needs.autofix-gate.outputs.go == 'true'` | checkout → download → `py -m loop.fix --pr ... --head-ref ${{ github.head_ref }} --base-ref origin/${{ github.base_ref }} --mode stub` → upload `loop-fix` |
| `reverify` | autofix-gate, fix | `${{ !cancelled() && needs.autofix-gate.result == 'success' && (needs.fix.result == 'success' \|\| needs.fix.result == 'skipped') }}` | checkout(fix 가 push 한 커밋까지) → make(`continue-on-error: true`) → `py -m loop.test_report --stage reverify ...` → upload `loop-reverify` |
| `merge-gate` | reverify | — | checkout → download → `py -m loop.gate --gate merge` → upload `loop-gate-merge` |
| `merge` | merge-gate | — | checkout → download → `py -m loop.finish merge --repo ... --pr ...` → upload `loop-merge` |
| `release-gate` | merge | — | checkout → download → `py -m loop.gate --gate release` → upload `loop-gate-release` |
| `release` | release-gate | — | checkout → download → `py -m loop.finish release --repo ... --pr ...` → upload `loop-release` |

공통 규칙:
- **모든 job 의 첫 step 은 checkout**: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1), `with: { ref: ${{ github.head_ref }}, fetch-depth: 0 }`. 이유: self-hosted 작업 폴더가 job 사이에 남으므로 checkout 의 clean 으로 이전 run 의 `out/` 을 지우고, `origin/<base>` 이력이 필요하다.
- download: `actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333` (v8.0.2), `with: { pattern: loop-*, merge-multiple: true, path: out }`.
- upload: `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9` (v7.0.2), `with: { name: loop-<단계>, path: out/<파일>, overwrite: true, if-no-files-found: error }`.
- `py -m loop.*` step 은 모두 `working-directory: ${{ vars.LOOP_HOME }}` 이고 `--workspace "${{ github.workspace }}"` 를 넘긴다. 값은 `${{ }}` 식으로 넣는다(셸 변수 문법에 기대지 않는다).
- make step: `shell: cmd`, `run: .\make.cmd test` (vsm `test.yml` 과 같은 명령). gcc 는 runner PC 에 이미 있다고 보고 `setup\setup_gcc.ps1` 을 부르기만 한다(캐시 action 은 쓰지 않는다 — self-hosted).
- `uses:` 는 위 세 action 만, 모두 40자리 SHA 고정.

### 2. `tests/test_loop_workflow.py` (PyYAML — 테스트에서만)
`loop/templates/pr-loop.yml` 을 `yaml.safe_load` 로 읽어 검사한다:
- 트리거: `pull_request.branches == ["master"]`, `types == ["opened", "synchronize", "reopened"]`(PyYAML 의 `on` → `True` 키 처리).
- `permissions == {"contents": "write", "pull-requests": "write"}` · concurrency group 에 `pull_request.number` 포함 · `cancel-in-progress` false.
- job 이름 9개와 needs 가 위 표와 정확히 같다.
- 모든 job: `runs-on == ["self-hosted", "vsm-loop"]`, `timeout-minutes <= 30`, 첫 step 이 checkout 이고 `fetch-depth: 0`, `ref` 에 `github.head_ref`.
- 모든 `uses:` 가 위 세 SHA 중 하나(정규식 `@[0-9a-f]{40}` + 허용 목록).
- test·reverify 의 make step: `continue-on-error: true`, `shell: cmd`.
- `fix.if` 에 `needs.autofix-gate.outputs.go == 'true'` · `reverify.if` 에 `needs.fix.result == 'skipped'` 와 `!cancelled()` · `autofix-gate.outputs.go` 정의.
- `py -m loop.` 를 쓰는 step 은 전부 `working-directory: ${{ vars.LOOP_HOME }}` 이고 `--workspace` 를 넘긴다.
- 각 단계 job 이 `loop-<단계>` 이름으로 upload 한다.
- 템플릿 안 `py -m loop.<모듈>` 의 모듈이 `loop/` 에 실제로 있다(파일 존재 검사).

## 요구사항 ID

R8

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/templates/pr-loop.yml`
- `tests/test_loop_workflow.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_workflow.py                  # 구조 테스트 통과
py -m pytest -q                                              # 전체 통과
py scripts/scope_check.py phases/1-loop-nogate/step1.md      # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 템플릿에서 reverify 의 `if` 식 중 `needs.fix.result == 'skipped'` 를 일부러 지우고 테스트가 실패하는지 확인한 뒤 되돌린다. download-artifact SHA 한 글자를 바꿔 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/1-loop-nogate/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 템플릿을 vsm 저장소에 복사하거나 GitHub 에 push 하지 마라. 이유: 설치는 phase 완료 후 메인 세션 E2E 몫.
- `secrets`·PAT·`workflow_dispatch` 트리거를 넣지 마라. 이유: ADR-006 — GITHUB_TOKEN 만, 새 run 자동 반복 방지.
- 게이트 기준·라벨 스위치를 넣지 마라. 이유: 다음 phase 몫.
- `loop/*.py` 를 수정하지 마라(인자가 맞지 않으면 blocked 로 보고). 이유: 이 step 범위 밖.
- 기존 테스트를 깨뜨리지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
