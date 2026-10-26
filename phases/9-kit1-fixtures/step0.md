# Step 0: nogate-fixtures

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-004: 외부 호출(git, gh)은 `runner` 주입 — 테스트는 fake runner
- ADR-006: PR 루프 — 단계 간 계약 `out/<단계>.json`, test·reverify 는 판정하지 않음, 1차 무게이트

## 배경

이 브랜치(`feat-9-kit1-fixtures`)는 태그 `kit-1`(무게이트 판) 위의 곁가지다. 2일차 실습 드라이런에서 「결함이 있는 PR 도 무게이트 루프에서는 merge · release 까지 간다 — 어디서 멈췄어야 하나?」 장면을 보여 주려면 결함 · 빌드 깨짐 fixture 가 필요한데, kit-1 에는 `basic` 하나뿐이다. 같은 fixture 가 이미 태그 `kit-5` 에 있으므로 그대로 가져온다. 이 step 이 끝나면 태그 `kit-1.1` 이 붙는다(메인 세션 몫).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/run_local.py` (`main(argv)` · `--fixture` · `--out` · FakeRunner)
- `loop/contract.py` (`read_stage`)
- `loop/gate.py` (무게이트 — 항상 PASS)
- `tests/test_loop_run_local.py` (기존 `basic` 시험 패턴)
- `tests/fixtures/loop/basic/` (fixture 구조: `expected-base.txt` · `test-results/*.xml` · `tests/expected_failures.txt`)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### 1. fixture 4종 가져오기 (데이터 복사만)

아래 명령으로 태그 `kit-5` 의 fixture 를 **바이트 그대로** 가져온다. 파일을 손으로 고치거나 새로 만들지 마라.

```bash
git checkout kit-5 -- tests/fixtures/loop/new-defect tests/fixtures/loop/fixed-listed tests/fixtures/loop/fixed-unlisted tests/fixtures/loop/build-broken
```

### 2. `tests/test_loop_run_local.py` 에 회귀 시험 추가

4종을 parametrize 한 시험을 기존 `test_run_local_basic` 아래에 더한다. fixture 마다 `main(["--fixture", <경로>, "--out", str(tmp_path)]) == 0` 이고, 다음을 확인한다:

- 게이트 3곳(`gate-autofix` · `gate-merge` · `gate-release` 계약)의 판정이 모두 PASS(go true) — 무게이트이므로 결함이 있어도 막지 않는다.
- `release` 계약 `prerelease is True`, `tag` 가 `loop-pr1-` 로 시작.
- `test` 계약 값(fixture 의 성격):

| fixture | 기대 |
|---|---|
| `new-defect` | `unexpected` 1건 · status ok |
| `fixed-listed` | `fixed` 1건 · `unexpected` 0건 |
| `fixed-unlisted` | `fixed` 1건 · `unexpected` 0건 |
| `build-broken` | status `error` |

계약 키 이름은 `loop/contract.py` · 각 단계 모듈에서 확인해 그대로 쓴다(추측 금지).

## 요구사항 ID

R7

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `tests/fixtures/loop/*`
- `tests/test_loop_run_local.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_loop_run_local.py                                      # 통과 (basic + 4종)
py -m pytest -q                                                                   # 전체 통과 (336 + 4)
py -m loop.run_local --fixture tests/fixtures/loop/new-defect                     # exit 0, merge · release 까지 감
py -m loop.run_local --fixture tests/fixtures/loop/build-broken                   # exit 0, merge · release 까지 감
git diff --stat kit-5 -- tests/fixtures/loop                                      # 출력 없음 (kit-5 와 바이트 동일)
py scripts/scope_check.py phases/9-kit1-fixtures/step0.md                         # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `new-defect` 기대를 `unexpected` 0건으로 일부러 바꿔 시험이 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
3. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
4. 결과에 따라 `phases/9-kit1-fixtures/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- `loop/*.py` 를 수정하지 마라. 이유: kit-1 의 무게이트 동작(결함이 있어도 끝까지 감)이 실습 장면 자체다. 시험이 실패하면 코드를 고치지 말고 error 처리하라.
- fixture 파일을 손으로 고치거나 kit-5 에 없는 fixture 를 만들지 마라. 이유: kit-5 와 같은 fixture 로 3일차에 「이번엔 멈춘다」를 비교한다.
- `tests/fixtures/loop/basic/` · `review-plan.json` 을 바꾸지 마라. 이유: 기존 kit-1 시험의 원천.
- 실제 `gh` · `claude` · `git push` 를 실행하지 마라. 이유: CLAUDE.md CRITICAL. 태그 · push 는 메인 세션이 Human 확인 뒤 한다.
- 기존 테스트를 깨뜨리지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
