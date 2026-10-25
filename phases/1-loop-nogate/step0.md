# Step 0: loop-skeleton

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-001: 구현은 Python 3.13 표준 라이브러리만
- ADR-004: 외부 호출(git, gh)은 `runner` 주입 — 테스트는 fake runner
- ADR-006: PR 루프 — 단계 간 계약 `out/<단계>.json`, test·reverify 는 판정하지 않음, 기준 목록은 base 브랜치 판, Fix 상한(PR 고유 커밋의 `Loop-Fix:` 트레일러), 1차 무게이트

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `pr_reviewer/proc.py` (`Runner` 타입, `run_process`)
- `pr_reviewer/junit.py` (참고만 — 이 step 은 통과 케이스까지 필요해서 재사용하지 않는다)
- `pr_reviewer/__main__.py` (CLI `main(argv, runner)` 패턴)
- `tests/test_cli.py` (fake runner 패턴)
- `C:\lab\2nd_NGV\vsm_test\tests\check_junit.py` (읽기 전용 — 식별자 `<스위트>::<케이스>` 와 ⓐⓑⓒ 정의의 원천. `:96-98`, `:139-158`)
- `C:\lab\2nd_NGV\vsm_test\test-results\*.xml`, `C:\lab\2nd_NGV\vsm_test\tests\expected_failures.txt` (읽기 전용 — fixture 원천)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

PR 루프의 **뼈대 전체**를 만든다. 게이트는 항상 통과(무게이트)다. 이 step 이 끝나면 `py -m loop.run_local` 로 전 단계가 로컬에서 한 바퀴 돌아야 한다(harness 원칙 8 — step 0 = 실행 가능한 최소 end-to-end).

### 공통 규칙

- 모든 단계 모듈은 `def main(argv: list[str] | None = None, runner: Runner = run_process) -> int` 와 `if __name__ == "__main__": sys.exit(main())` 를 가진다. `Runner`/`run_process` 는 `pr_reviewer.proc` 에서 가져온다.
- 공통 인자 `--workspace PATH`(vsm 저장소 checkout 경로). 출력 폴더는 `<workspace>/out`(없으면 만든다).
- git 은 `["git", "-C", workspace, ...]`, gh 는 `["gh", ..., "-R", repo]` 로 부른다(cwd 를 쓰지 않는다 — `run_process` 에 cwd 인자가 없다).
- 단계끼리는 프로세스 경계라 **계약 JSON(`loop/contract.py` 로 검증)으로만** 주고받는다.
- 실패를 빈 값으로 삼키지 않는다: 읽어야 할 계약 파일이 없거나 키가 빠지면 `ContractError` → stderr 메시지 + exit 1.
- 모든 파일 I/O 는 `encoding="utf-8"`, JSON 은 `ensure_ascii=False, indent=2`.
- `GITHUB_OUTPUT` 환경변수가 있으면 `key=value` 줄을 append 하는 헬퍼(`contract.write_github_output(key, value)`)를 두고, 없으면 아무것도 하지 않는다.

### 1. `loop/__init__.py`
빈 파일 또는 docstring 한 줄.

### 2. `loop/contract.py`
```python
class ContractError(Exception): ...
STAGE_KEYS: dict[str, tuple[str, ...]]   # 아래 표
def stage_path(out_dir: Path, name: str) -> Path            # out_dir / f"{name}.json"
def write_stage(out_dir: Path, name: str, data: dict) -> Path   # 필수 키 검사 후 쓰기
def read_stage(out_dir: Path, name: str) -> dict                # 파일 없음 · JSON 깨짐 · 필수 키 누락 → ContractError
def write_github_output(key: str, value: str) -> None
```
이름(name) → 필수 키 (`stage` 값은 name 과 같아야 한다):

| name | 필수 키 |
|---|---|
| `test`, `reverify` | `stage, status, make_outcome, total, failed, unexpected, fixed, missing, head_sha, expected_base, expected_head` |
| `review` | `stage, status, mode, counts, critical_by_category, event, posted, errors` |
| `gate-autofix`, `gate-merge`, `gate-release` | `stage, gate, go, decision, reason, forced, degraded` |
| `fix` | `stage, status, mode, action, commit_sha, attempt` |
| `merge` | `stage, merged, merge_sha, noop` |
| `release` | `stage, tag, url, prerelease, reused, degraded` |

`status` 값은 `"ok"` 또는 `"error"`. 목록 키(`failed` 등)는 문자열 리스트. `go`·`forced`·`degraded`·`posted`·`merged`·`noop`·`prerelease`·`reused` 는 bool. 타입이 틀리면 ContractError.

### 3. `loop/test_report.py` (test · reverify 단계 — 판정하지 않는다)
인자: `--workspace`, `--stage {test,reverify}`, `--make-outcome TEXT`(workflow 의 `steps.make.outcome` 그대로 기록), `--base-ref REF`(예: `origin/master`), `--results DIR`(기본 `<workspace>/test-results`), `--expect-path PATH`(기본 `tests/expected_failures.txt`).
- 결과 XML(`<results>/*.xml`, 정렬)에서 **모든 testcase** 를 읽어 식별자 `<스위트>::<케이스>` → 통과/실패. 식별자 규칙은 `check_junit.py` 와 같게 맞춘다(이 파일을 읽고 확인하라). `<failure>` 또는 `<error>` 가 있으면 실패.
- 기준 목록 = **base 판**: `git -C <ws> show <base-ref>:<expect-path>` 의 stdout. head 판 = `<workspace>/<expect-path>` 파일. 둘 다 빈 줄과 `#` 줄 제외.
- 분류(base 목록 기준): `unexpected` = 실패했는데 base 목록에 없음(ⓐ) · `fixed` = base 목록에 있는데 통과(ⓑ) · `missing` = base 목록에 있는데 결과에 없음(ⓒ). `failed` = 실패 전체. 모두 정렬된 리스트.
- `head_sha` = `git -C <ws> rev-parse HEAD`.
- `status: "error"` + `reason` 키(추가 키 허용) 인 경우: XML 0개 · XML 파싱 실패 · testcase 0개 · `git show` 실패. 이때도 계약 파일은 쓰고 **exit 0**(판정은 게이트 몫). 계약 파일을 못 쓰면 exit 1.
- 정상: `status: "ok"`, exit 0.

### 4. `loop/review.py` (이 step 은 stub 만)
인자: `--workspace`, `--mode {stub}`, `--repo OWNER/REPO`, `--pr N`.
stub: `review.json` = `{stage:"review", status:"ok", mode:"stub", counts:{critical:0, major:1, minor:1}, critical_by_category:{}, event:"COMMENT", posted:false, errors:[]}`. upstream `test.json` 을 read_stage 로 읽어(없으면 exit 1) 계약 체인을 확인한다.

### 5. `loop/gate.py` (1차 무게이트)
인자: `--workspace`, `--gate {autofix,merge,release}`.
- 먼저 upstream 을 read_stage 로 읽는다: autofix ← `test`, `review` / merge ← `reverify` / release ← `merge`, `reverify`. 없으면 exit 1(fail-closed).
- 결과: `{stage:"gate-<gate>", gate, go:true, decision:"PASS", reason:"무게이트(1차 뼈대)", forced:false, degraded:false}` 를 쓰고 `write_github_output("go", "true")`.
- exit code 규칙(다음 step 들이 쓴다 — 지금 구현해 둔다): merge·release 게이트는 `go` 가 false 면 exit 1, autofix 게이트는 항상 exit 0. 이 step 에서는 항상 go true 다.

### 6. `loop/fix.py` (stub · 안전 레일 Fix 상한)
인자: `--workspace`, `--pr N`, `--head-ref BRANCH`, `--base-ref REF`, `--mode {stub}`.
- Fix 상한: `git -C <ws> log --format=%B <base-ref>..HEAD` 출력에 `Loop-Fix:` 로 시작하는 줄이 있으면 `action:"NO_ACTION"`, `commit_sha:""`, `attempt:1` 을 쓰고 exit 0. **base 이력(`<base-ref>` 이전 커밋)은 세지 않는다.**
- 아니면: `head7` = `git rev-parse --short=7 HEAD` → 고유 파일 `<ws>/.loop/fix-pr<N>-<head7>.md` 에 한 줄(무엇을 했는지) 쓰기 → `git -C <ws> add -- .loop/fix-pr<N>-<head7>.md` → `git -C <ws> -c user.name=loop-bot -c user.email=loop-bot@users.noreply.github.com commit -m "chore(loop): stub fix for PR #<N>" -m "Loop-Fix: 1"` → `git -C <ws> push origin HEAD:<head-ref>` → `commit_sha` = `git rev-parse HEAD`. `action:"COMMITTED"`, `attempt:1`.
- git 명령이 실패하면 `status:"error"`, `action:"FAILED"`, `reason` 을 쓰고 exit 1.

### 7. `loop/finish.py` (merge · release — 멱등)
`py -m loop.finish merge|release --workspace PATH --repo OWNER/REPO --pr N`
- merge: `reverify.json` 을 읽어 `head_sha` 를 얻는다. `gh pr view <N> -R <repo> --json state,mergeCommit` → `state == "MERGED"` 면 `noop:true, merged:true, merge_sha:<mergeCommit.oid>`. 아니면 `gh pr merge <N> -R <repo> --merge --match-head-commit <head_sha>` → 다시 view 해서 `merge_sha`. 실패하면 `merged:false`, `reason`, exit 1.
- release: `merge.json` 을 읽어 `merged` 가 false 면 exit 1. `tag = f"loop-pr{N}-{merge_sha[:7]}"`. `gh release view <tag> -R <repo> --json url` 이 성공하면 `reused:true` 로 그 url. 아니면 `out/release-notes.md`(각 단계 JSON 의 status/decision 요약, degraded 가 하나라도 true 면 표시)를 쓰고 `gh release create <tag> -R <repo> --target <merge_sha> --prerelease --title "loop PR #<N>" --notes-file <notes>` → view 로 url. `prerelease` 는 항상 true. `degraded` = 읽은 gate 파일 중 하나라도 degraded.

### 8. `loop/run_local.py`
`py -m loop.run_local --fixture DIR [--out DIR]`
- 임시 workspace(`tempfile.TemporaryDirectory`, `--out` 을 주면 그 폴더)에 fixture 의 `test-results/*.xml` 과 `tests/expected_failures.txt` 를 복사한다.
- 결정적으로 답하는 `FakeRunner`(git show → fixture `expected-base.txt`, rev-parse → 고정 sha, log → 빈 문자열, add/commit/push → 성공, gh pr view → 처음 OPEN 다음 MERGED + mergeCommit oid, gh pr merge → 성공, gh release view → 처음 실패 다음 성공 url, gh release create → 성공)를 만든다.
- 순서대로 각 모듈의 `main(argv, runner=fake)` 를 호출한다: test → review → gate autofix → fix → test_report(reverify) → gate merge → finish merge → gate release → finish release.
- 모든 단계가 0 을 돌려주고 `release.json` 이 read_stage 로 읽히면 단계별 한 줄 요약을 찍고 exit 0. 아니면 실패 단계 이름과 함께 exit 1.

### 9. fixture `tests/fixtures/loop/basic/`
- `test-results/` ← `C:\lab\2nd_NGV\vsm_test\test-results\*.xml` 복사(원본은 고치지 않는다)
- `tests/expected_failures.txt` ← `C:\lab\2nd_NGV\vsm_test\tests\expected_failures.txt` 복사
- `expected-base.txt` ← 같은 파일 복사(base 판 역할)

### 10. 테스트 (fake runner · 실제 git/gh 실행 금지)
- `tests/test_loop_contract.py`: 왕복(write→read), 필수 키 누락 · 파일 없음 · JSON 깨짐 · bool 타입 오류 → ContractError, `write_github_output` 이 env 있을 때만 쓴다.
- `tests/test_loop_test_report.py`: basic fixture → unexpected/fixed/missing 모두 빈 리스트, failed 8건. 통과 케이스 하나를 실패로 바꾼 XML → unexpected 1건. base 목록에만 있는 케이스가 통과 → fixed 1건. base 목록 케이스가 결과에 없음 → missing 1건. XML 0개 → status error · exit 0. `git show` 실패 → status error. 같은 XML·같은 목록에서 `check_junit.py` 의 ⓐⓑⓒ 와 판정이 일치함을 식 수준으로 확인하는 테스트 1건(check_junit.py 를 import 하지 말고, 그 정의를 주석으로 인용).
- `tests/test_loop_stages.py`: review stub · gate(upstream 없으면 exit 1, 있으면 go true + GITHUB_OUTPUT) · fix(PR 고유 커밋에 트레일러 → NO_ACTION · base 이력 트레일러는 무시 · 고유 파일명 · commit/push 인자 · git 실패 → exit 1) · finish(MERGED 면 noop · `--match-head-commit` 인자 · release 태그 이미 있으면 reused · `--target <merge_sha>` · `--prerelease`).
- `tests/test_loop_run_local.py`: basic fixture 로 exit 0, release.json 존재.

## 요구사항 ID

R7

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `loop/__init__.py`
- `loop/contract.py`
- `loop/test_report.py`
- `loop/review.py`
- `loop/gate.py`
- `loop/fix.py`
- `loop/finish.py`
- `loop/run_local.py`
- `tests/test_loop_contract.py`
- `tests/test_loop_test_report.py`
- `tests/test_loop_stages.py`
- `tests/test_loop_run_local.py`
- `tests/fixtures/loop/*`

## Acceptance Criteria

```bash
py -m pytest -q                                              # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/basic     # exit 0 (전 단계 한 바퀴)
py scripts/scope_check.py phases/1-loop-nogate/step0.md      # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `loop/fix.py` 의 Fix 상한 검사 범위를 `<base-ref>..HEAD` 에서 전체 이력으로 일부러 바꿔 테스트가 실패하는지 확인하고 되돌린다. `loop/contract.py` 의 필수 키 검사를 일부러 끄고 테스트가 실패하는지 확인하고 되돌린다. 결과를 summary 에 적는다.
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

- 실제 `git`·`gh`·`claude`·`make` 를 실행하지 마라(테스트와 run_local 모두 fake runner). 이유: 실제 저장소 변경과 과금 방지, CLAUDE.md CRITICAL.
- 게이트에 기준(테스트 결과로 막기 등)을 넣지 마라. 이유: 1차 무게이트 — 기준은 다음 phase 몫.
- `pr_reviewer/` 를 수정하지 마라. 이유: 이 step 범위 밖.
- `C:\lab\2nd_NGV\vsm_test` 의 파일을 수정하지 마라(읽기·복사만).
- 기존 테스트를 깨뜨리지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
