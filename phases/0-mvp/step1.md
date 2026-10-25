# Step 1: github-client

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-003: GitHub I/O는 gh CLI (조회·artifact·게시 명령 형식)
- ADR-004: runner 주입으로 외부 호출 격리
- ADR-005: 자기 PR이면 REQUEST_CHANGES 불가 → 현재 사용자 조회 필요

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `pr_reviewer/models.py` (PullRequest, InlineComment 계약)
- `pr_reviewer/proc.py` (Runner, run_process)
- `pyproject.toml`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/github.py`

```python
class GhError(Exception): ...   # gh 비정상 종료 시. 메시지에 명령 요약과 stderr 포함

def fetch_pull_request(owner: str, repo: str, number: int, runner: Runner = run_process) -> PullRequest:
    """gh api repos/{o}/{r}/pulls/{n} → head.sha, user.login, html_url."""

def fetch_diff(owner: str, repo: str, number: int, runner: Runner = run_process) -> str:
    """gh pr diff {n} -R {o}/{r}."""

def current_user(runner: Runner = run_process) -> str:
    """gh api user → login."""

def download_junit_reports(pr: PullRequest, artifact_name: str, dest_dir: Path,
                           runner: Runner = run_process) -> list[Path]:
    """head SHA의 완료된 최신 workflow run에서 artifact를 dest_dir에 받고, 그 안의 *.xml 경로 목록(재귀, 정렬)을 반환."""

def post_review(pr: PullRequest, event: str, body: str, comments: Sequence[InlineComment],
                runner: Runner = run_process) -> None:
    """POST repos/{o}/{r}/pulls/{n}/reviews. JSON 본문은 `gh api ... --method POST --input -`로 stdin 전달."""

def post_issue_comment(pr: PullRequest, body: str, runner: Runner = run_process) -> None:
    """POST repos/{o}/{r}/issues/{n}/comments. 본문은 stdin JSON {"body": ...}."""
```

핵심 규칙:
- `download_junit_reports`
  - `gh run list -R {o}/{r} --commit {sha} --json databaseId,status,conclusion,createdAt`로 run을 찾는다. `status == "completed"`인 run 중 `createdAt`이 가장 최근인 것을 고른다.
  - 완료된 run이 없으면 `[]`를 반환한다(예외 금지). 이유: 테스트 결과가 없어도 리뷰는 진행해야 한다(R2).
  - `gh run download {id} -R {o}/{r} -n {artifact_name} -D {dest_dir}`가 실패하면(artifact 없음 등) `[]`를 반환한다(예외 금지).
  - `gh run list` 자체가 실패하면(권한 등) `GhError`를 던진다.
- `post_review`
  - 페이로드: `{"commit_id": pr.head_sha, "event": event, "body": body, "comments": [{"path","line","side":"RIGHT","body"}]}`.
  - `event`는 `"COMMENT"` 또는 `"REQUEST_CHANGES"`만 허용하고, 그 외 값은 `ValueError`. 이유: 실수로 `APPROVE`가 게시되면 안 된다.
  - commentable line 필터링은 이 모듈에서 하지 않는다(aggregate 책임). 받은 comments를 그대로 보낸다.
- 모든 함수는 runner 반환 `returncode != 0`이면 `GhError`를 던진다(위 `[]` 반환 예외 제외).
- JSON 직렬화는 `ensure_ascii=False`. 이유: 한국어 코멘트.

### `tests/test_github.py`
- fake runner(호출된 args/input을 기록하고 미리 정한 CompletedProcess 반환)로만 테스트한다.
- 최소 케이스: PR 메타 파싱, diff 반환, user login, run 선택(미완료 run 무시·최신 선택), run 없음 → `[]`, download 실패 → `[]`, run list 실패 → GhError, 다운로드된 xml 경로 수집(`tmp_path`에 fake runner가 파일 생성), review 페이로드(side=RIGHT, commit_id, 한국어 그대로), 잘못된 event → ValueError, issue comment 페이로드, 비정상 종료 → GhError.

## 요구사항 ID

R1, R2, R5

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/github.py`
- `tests/test_github.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_github.py   # gh 래퍼 테스트 통과 (fake runner만 사용)
py -m pytest -q                        # 전체 통과
py scripts/scope_check.py phases/0-mvp/step1.md   # 범위 이탈 없음
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

- 실제 `gh`를 실행하는 테스트를 쓰지 마라(동작 확인용 수동 실행 포함). 이유: CLAUDE.md CRITICAL, 실제 게시 위험.
- `requests`/`urllib`로 GitHub API를 직접 호출하지 마라. 이유: ADR-003, 토큰 관리 회피.
- `models.py`를 수정하지 마라. 이유: 이 step의 범위 밖이며 다른 step의 계약이다.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
