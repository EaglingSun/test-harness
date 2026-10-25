# Step 6: cli-wiring

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-001: `py -m pr_reviewer`, argparse
- ADR-003: 게시 순서 (PR Review → Issue comment)
- ADR-004: runner 주입 (CLI도 runner를 받아 테스트에서 fake 사용)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `docs/ARCHITECTURE.md` (데이터 흐름 — 이 step이 그대로 조립한다)
- `pr_reviewer/models.py`
- `pr_reviewer/proc.py`
- `pr_reviewer/diff.py`
- `pr_reviewer/github.py`
- `pr_reviewer/junit.py`
- `pr_reviewer/runner.py`
- `pr_reviewer/agents.py`
- `pr_reviewer/aggregate.py`
- `tests/test_agents.py` (fake runner로 gh/claude 명령을 판별하는 패턴)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/__main__.py`

```python
def main(argv: Sequence[str] | None = None, runner: Runner = run_process) -> int: ...

if __name__ == "__main__":
    sys.exit(main())
```

인자: `repo`(`owner/repo` 형식, 아니면 argparse 에러), `number`(int), `--dry-run`, `--junit-artifact`(기본 `junit-results`).

흐름 (ARCHITECTURE 데이터 흐름 그대로):
1. `fetch_pull_request` → `fetch_diff` → `current_user` → `parse_commentable_lines`.
2. `tempfile.TemporaryDirectory()` 안에서 `download_junit_reports`를 호출한다. XML이 있으면 `parse_junit_files`, 없으면 `report=None`. `JUnitParseError`가 나면 `report=None`으로 두고 stderr에 경고를 남긴다(리뷰는 계속).
3. `run_all_agents(pr, diff, report, runner)` → `build_review_plan(pr, results, commentable, user, report)`.
4. `--dry-run`: 아래 JSON을 stdout에 출력하고 게시 없이 0을 반환한다(`ensure_ascii=False`, indent=2).
   `{"event", "review_body", "inline": [{"path","line","body"}], "summary_markdown", "agents": [{"category","findings","error","skipped_reason"}]}`
5. 게시: `post_review(pr, plan.event, plan.review_body, plan.inline)` → `post_issue_comment(pr, plan.summary_markdown)`.
   - `post_review`가 `GhError`이면 요약 끝에 "인라인 리뷰 게시 실패: <에러>"를 붙여 요약은 게시하고 1을 반환한다. 이유: 최소한 요약 결과는 PR에 남긴다.
   - 성공하면 stdout에 PR URL과 event, 인라인 건수를 한 줄로 출력하고 0을 반환한다.
6. 1번 단계에서 `GhError`가 나면 stderr에 메시지를 쓰고 1을 반환한다(traceback 금지).
- Windows 콘솔 인코딩: 출력 전에 `sys.stdout.reconfigure(encoding="utf-8")`를 시도하되 실패해도 무시한다.

### `tests/test_cli.py`
- 하나의 fake runner가 gh/claude 명령을 args로 판별해 고정 응답을 돌려준다(PR 메타, diff, user, run list, run download는 `-D` 경로에 XML 파일 생성, claude 각 단계 JSON, POST 기록).
- 최소 케이스:
  - `--dry-run` → POST 호출 0회, stdout JSON에 event/inline/summary 포함, exit 0
  - 정상 게시 → reviews POST 다음 issues comments POST 순서, exit 0
  - JUnit run 없음 → A skipped가 요약에 표시, 나머지 진행
  - 에이전트 하나 claude 실패 → 게시는 진행, 요약에 실행 실패 표시
  - post_review 실패 → 요약에 실패 문구 포함해 게시, exit 1
  - PR 조회 실패 → exit 1, POST 없음
  - 잘못된 repo 인자 → SystemExit

## 요구사항 ID

R6, R5

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/__main__.py`
- `tests/test_cli.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_cli.py   # CLI 조립 테스트 통과 (fake runner만 사용)
py -m pytest -q                     # 전체 통과
py -m pr_reviewer --help            # 인자 도움말 출력, exit 0
py scripts/scope_check.py phases/0-mvp/step6.md   # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
3. 결과에 따라 `phases/0-mvp/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- 실제 PR을 대상으로 `py -m pr_reviewer`를 실행하지 마라. `--dry-run`도 마찬가지다. 이유: dry-run이라도 실제 claude 과금 호출이 일어나고, E2E는 phase 완료 후 Human 확인으로만 한다(CLAUDE.md CRITICAL).
- 다른 `pr_reviewer/*.py` 모듈을 수정하지 마라. 계약이 맞지 않으면 blocked 처리하라. 이유: 범위 밖, 각 step의 계약.
- 재시도, 로깅 프레임워크, 설정 파일을 추가하지 마라. 이유: MVP 범위 밖.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
