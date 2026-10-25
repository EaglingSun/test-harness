# Step 2: reviewer-cli-options

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-003: GitHub I/O 는 gh CLI (`gh api user` 로 현재 사용자 조회)
- ADR-004: 외부 호출은 runner 주입
- ADR-006: PR 루프는 같은 run 안에서 리뷰한다 — 완료된 run 의 artifact 를 기다릴 수 없다. 토큰은 GITHUB_TOKEN

## 읽어야 할 파일

먼저 아래 파일들을 읽고 설계 의도를 파악하라:

- `pr_reviewer/__main__.py` (`_parse_args`, `_load_report`, `_dry_run_payload`, `main`)
- `pr_reviewer/github.py` (`current_user`, `download_junit_reports`)
- `pr_reviewer/junit.py` (`parse_junit_files`, `JUnitParseError`)
- `tests/test_cli.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

`pr_reviewer` CLI 에 옵션 3개를 더한다. 옵션을 주지 않으면 **지금 동작이 그대로**여야 한다.

1. `--junit-dir PATH`: 주면 artifact 다운로드(`download_junit_reports`)를 하지 않고 `PATH/*.xml`(정렬)을 `parse_junit_files` 로 읽는다. 이유: PR 루프는 같은 run 안에서 리뷰하므로 아직 완료되지 않은 run 의 artifact 를 받을 수 없다(`download_junit_reports` 는 `status == "completed"` run 만 고른다).
   - XML 이 0개면 "결과 없음"(report None)으로 진행하되 stderr 에 `경고: --junit-dir 에 JUnit XML 이 없다: <PATH>` 를 찍는다(조용히 넘기지 않는다).
   - 파싱 실패는 지금 `_load_report` 와 같은 경고 + report None.
   - `--junit-dir` 와 `--junit-artifact` 를 함께 주면 `--junit-dir` 가 이긴다(help 에 적는다).
2. `--plan-out PATH`: 리뷰 계획 payload(`_dry_run_payload` 와 같은 dict)를 PATH 에 UTF-8 JSON(`ensure_ascii=False, indent=2`)으로 쓴다. `--dry-run` 이든 실제 게시든 **게시 전에** 쓴다(게시가 실패해도 계획 파일은 남는다).
3. `--current-user LOGIN`: 주면 `current_user(runner)`(`gh api user`)를 부르지 않고 LOGIN 을 현재 사용자로 쓴다. 이유: GITHUB_TOKEN 으로는 `GET /user` 가 막혀 지금 CLI 가 "PR 조회 실패" 로 끝난다.

### `tests/test_cli.py` 에 추가 (fake runner)
- `--junit-dir` 에 XML 2개 → `gh run list`/`gh run download` 가 호출되지 않고, 에이전트 A 프롬프트(stdin)에 실패 테스트가 들어간다.
- `--junit-dir` 에 XML 0개 → stderr 경고, A skip(`skipped_reason`), exit 0(dry-run).
- `--plan-out` + `--dry-run` → 파일 내용이 stdout payload 와 같다.
- `--plan-out` + 실제 게시 + 리뷰 게시 실패 → 파일이 남아 있고 exit 1.
- `--current-user bot` → `gh api user` 가 호출되지 않는다. PR 작성자 == `bot` 이면 자기 PR 규칙(COMMENT 대체)이 적용된다.
- 옵션 없이 실행 → 기존 테스트 그대로 통과(회귀 없음).

## 요구사항 ID

R9

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/__main__.py`
- `tests/test_cli.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_cli.py                            # 추가분 포함 통과
py -m pytest -q                                              # 전체 통과
py scripts/scope_check.py phases/1-loop-nogate/step2.md      # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. **검출력 확인(red-green-revert)**: `--current-user` 를 받아도 `current_user(runner)` 를 부르도록 일부러 바꿔 테스트가 실패하는지 확인한 뒤 되돌린다. 결과를 summary 에 적는다.
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

- 실제 `gh`·`claude` 를 실행하지 마라. 이유: 실제 게시와 과금 방지(CLAUDE.md CRITICAL).
- 심각도 규칙·병합·게시 event 판정(`aggregate.py`)을 바꾸지 마라. 이유: ADR-005 승인 정책.
- `github.py`·`junit.py` 의 기존 함수 시그니처를 바꾸지 마라. 이유: 기존 테스트와 계약 유지.
- 기존 테스트의 assert 를 삭제하거나 약화하지 마라.
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
