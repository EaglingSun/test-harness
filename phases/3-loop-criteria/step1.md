# Step 1: fix-real-mode

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-002: claude CLI headless, 프롬프트는 stdin
- ADR-004: 외부 호출은 runner 주입
- ADR-006: Fix 상한 1회(PR 고유 커밋의 `Loop-Fix:` 트레일러) · GITHUB_TOKEN push
- ADR-007: Fix real = `claude -p` 편집, **편집 허용 `src/`·`include/` 만**(채점 기준 `tests/expected_failures.txt` 금지), 바뀐 경로는 코드로 검사, cwd = workspace

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `loop/fix.py` (stub · Fix 상한 · commit/push)
- `pr_reviewer/proc.py` (`run_process`)
- `pr_reviewer/runner.py` (`run_claude` 의 `--allowedTools`/`--disallowedTools` 인자 꼴)
- `loop/templates/pr-loop.yml` (fix job)
- `tests/test_loop_stages.py` (fix 테스트)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### 1. `pr_reviewer/proc.py`
`run_process(args, input=None, timeout=900, cwd=None)` — 키워드 `cwd` 를 더해 `subprocess.run` 에 넘긴다. 기존 호출(인자 2개)은 그대로 동작해야 한다.

### 2. `loop/fix.py` — `--mode real`
- choices = `stub`, `real`. stub 동작은 그대로.
- real 은 Fix 상한 검사(기존) 뒤에:
  1. 실패 정보 조립(코드로 결정적으로): `out/test.json` 의 `unexpected` 식별자 목록 + `out/` 의 JUnit XML(`loop-junit` artifact)에서 그 케이스들의 `<failure message>` + `<workspace>/test_ref/요구사항.md` 본문.
  2. 프롬프트(stdin): 위 정보 + 지시 「`src/`·`include/` 아래 파일만 최소한으로 고쳐 위 테스트가 요구사항대로 통과하게 하라. 테스트(`tests/`)·`tests/expected_failures.txt`·그 밖 파일은 고치지 마라. 빌드·실행은 하지 마라.」
  3. claude 실행: `["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Read", "Edit", "Glob", "Grep", "--disallowedTools", "Bash", "Write"]`, **cwd = workspace**, timeout 600초. claude 용 runner 는 `functools.partial(run_process, cwd=workspace, timeout=600)` 를 기본값으로 하고 테스트는 fake 를 넘긴다(`main(argv, runner, claude_runner=None)`).
  4. 바뀐 경로 검사(코드): `git -C <ws> status --porcelain` → 바뀐 파일이 0개면 `action: "NO_ACTION"`, `reason: "Fix 가 변경하지 않음"`, exit 0. `src/`·`include/` 밖 파일이 하나라도 바뀌었으면 `git -C <ws> checkout -- .` 와 `git -C <ws> clean -fd -- .`(바뀐 것 되돌림) 후 `action: "FAILED"`, `status: "error"`, reason 에 경로, exit 1.
  5. 통과하면 stub 과 같은 commit(`-m "fix(loop): auto-fix for PR #<N>" -m "Loop-Fix: 1"`) · push. `fix.json` 에 `changed_files` 키 추가.
  6. claude 가 비정상 종료 · timeout 이면 `action: "FAILED"`, `status: "error"`, exit 1(원시 stdout/stderr 앞 2000자를 `out/fix-claude-raw.txt` 에 남긴다 — 원시 응답 로깅).

### 3. `loop/templates/pr-loop.yml`
- fix job 의 `--mode stub` → `--mode ${{ vars.LOOP_FIX_MODE || 'stub' }}`. 머리 주석 변수 목록에 `LOOP_FIX_MODE`(비우면 stub) 추가.

### 4. 테스트 (fake runner · 실제 claude/git 실행 금지)
- `tests/test_loop_fix_real.py`: claude argv · cwd 가 workspace 인 runner 사용 · 프롬프트에 unexpected 식별자·failure message·요구사항 본문·금지 지시가 들어간다 · 변경 0 → NO_ACTION · `tests/expected_failures.txt` 변경 → 되돌림 + FAILED exit 1 · `src/` 만 변경 → commit/push + changed_files · claude 실패 → FAILED + raw 파일 · Fix 상한(트레일러) → claude 를 부르지 않는다.
- `tests/test_loop_workflow.py`: fix step 이 `vars.LOOP_FIX_MODE` 를 쓴다.
- `tests/test_runner.py` 또는 새 테스트: `run_process` 가 `cwd` 를 `subprocess.run` 에 넘긴다(monkeypatch) · 기존 호출 회귀 없음.

## 요구사항 ID

R13

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/proc.py`
- `loop/fix.py`
- `loop/templates/pr-loop.yml`
- `tests/test_loop_fix_real.py`
- `tests/test_loop_workflow.py`
- `tests/test_loop_stages.py`
- `tests/test_runner.py`
- `tests/test_proc.py`
- `tests/fixtures/loop/*`

## Acceptance Criteria

```bash
py -m pytest -q                                                   # 전체 통과
py -m loop.run_local --fixture tests/fixtures/loop/new-defect     # exit 0 (stub 경로 회귀 없음)
py scripts/scope_check.py phases/3-loop-criteria/step1.md         # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: 바뀐 경로 검사에서 `src/` 밖 판정을 일부러 끄고 `expected_failures.txt` 변경 테스트가 실패하는지, Fix 상한 검사를 claude 호출 뒤로 옮겨 「claude 를 부르지 않는다」 테스트가 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
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

- 실제 `claude`·`git`·`gh` 를 실행하지 마라. 이유: 과금·실제 저장소 변경 방지(CLAUDE.md CRITICAL). real 모드의 실제 실행은 phase 완료 후 메인 세션 E2E 몫.
- Fix 결과가 맞는지 LLM 으로 판정하지 마라. 이유: 판정은 reverify + merge 게이트(결정적 코드) 몫.
- `proc.run_process` 의 기존 인자 순서·기본값을 바꾸지 마라. 이유: 기존 호출 회귀 방지.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
