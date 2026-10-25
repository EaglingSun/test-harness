# Step 3: review-real-mode

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-004: 외부 호출은 runner 주입
- ADR-005: 심각도 정책 (원천 등급 — 이 step 은 바꾸지 않는다)
- ADR-006: 단계 간 계약 `review.json`, GITHUB_TOKEN 이라 현재 사용자는 `github-actions[bot]`

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/review.py`, `loop/contract.py` (step 0)
- `pr_reviewer/__main__.py` (step 2 의 `--junit-dir`, `--plan-out`, `--current-user` 와 `_dry_run_payload` 키)
- `pr_reviewer/models.py` (`Finding` 필드 — `severity`, `category`)
- `loop/templates/pr-loop.yml` (review job 이 넘기는 인자 — step 1)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

`loop/review.py` 에 `--mode real` 을 더한다(stub 동작은 그대로).

- 인자 추가: `--current-user LOGIN`(기본 `github-actions[bot]`). `--mode` choices = `stub`, `real`.
- real:
  1. `out/review-plan.json` 경로를 정하고 runner 로 `[sys.executable, "-m", "pr_reviewer", <repo>, <pr>, "--junit-dir", <out_dir>, "--plan-out", <plan>, "--current-user", <login>]` 를 실행한다. workflow 의 `working-directory` 가 test_harness 루트라 `-m pr_reviewer` 가 잡힌다(cwd 인자는 쓰지 않는다). JUnit XML 은 test job 이 올린 `loop-junit` 을 download 해 `out/` 에 있다.
  2. plan 파일을 읽어 변환한다:
     - `counts` = `agents[].findings[].severity` 를 `critical/major/minor` 별로 센 값(**원천 등급 · 집계 전** — 키 이름 옆 주석과 review.json 의 `counts_basis: "agent_raw"` 키로 밝힌다).
     - `critical_by_category` = critical 을 category 별로 센 dict.
     - `event` = plan 의 `event`.
     - `errors` = `agents[].error` 중 None 이 아닌 것 + 프로세스 실패 메시지.
     - `posted` = 프로세스 exit 0.
  3. 프로세스 exit ≠ 0 이거나 plan 파일이 없으면 `status: "error"`, `posted: false`, `errors` 에 stderr 마지막 줄을 넣고 계약 파일을 쓴 뒤 **exit 0**(판정은 게이트 몫 · 리뷰 실패가 루프 전체를 멈추지 않게 — 대신 status error 로 드러낸다).
  4. plan 파일은 있는데 JSON 이 깨졌으면 같은 error 처리.

### `tests/test_loop_review.py` (fake runner · 실제 실행 금지)
- real 모드 argv 가 위와 정확히 같다(`sys.executable` 포함).
- fixture plan(`tests/fixtures/loop/review-plan.json` — critical 1 · major 2 · minor 1, 에이전트 error 1개)을 돌려주면 counts · critical_by_category · errors · posted 가 맞다.
- 프로세스 exit 1 + plan 없음 → status error, posted false, exit 0.
- 깨진 plan JSON → status error.
- stub 모드는 step 0 과 같은 결과(회귀 없음).

## 요구사항 ID

R10

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/review.py`
- `tests/test_loop_review.py`
- `tests/fixtures/loop/*`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_review.py                    # 통과
py -m pytest -q                                              # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/basic     # exit 0 (stub 경로 회귀 없음)
py scripts/scope_check.py phases/1-loop-nogate/step3.md      # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 프로세스 실패 시 `status` 를 `"ok"` 로 쓰도록 일부러 바꿔 테스트가 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
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

- 실제 `py -m pr_reviewer`·`gh`·`claude` 를 실행하지 마라. 이유: 실제 게시와 과금 방지(CLAUDE.md CRITICAL). real 모드의 실제 실행은 phase 완료 후 메인 세션 E2E 몫.
- `pr_reviewer/` 를 수정하지 마라. 이유: 이 step 범위 밖(옵션은 step 2 에서 끝났다).
- review 결과로 게이트를 막는 규칙을 넣지 마라. 이유: 게이트 기준은 다음 phase 몫.
- 기존 테스트를 깨뜨리지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
