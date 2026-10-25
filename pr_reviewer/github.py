"""gh CLI 래퍼: PR/diff/사용자 조회, JUnit artifact 다운로드, 리뷰·코멘트 게시 (R1, R2, R5, ADR-003)."""

import json
import subprocess
from pathlib import Path
from typing import Sequence

from pr_reviewer.models import InlineComment, PullRequest
from pr_reviewer.proc import Runner, run_process

_ALLOWED_EVENTS = ("COMMENT", "REQUEST_CHANGES")  # APPROVE 오게시 방지


class GhError(Exception):
    """gh 비정상 종료."""


def _run(args: list[str], runner: Runner, input: str | None = None) -> subprocess.CompletedProcess:
    proc = runner(args, input)
    if proc.returncode != 0:
        raise GhError(f"`{' '.join(args)}` failed (exit {proc.returncode}): {(proc.stderr or '').strip()}")
    return proc


def _post_json(endpoint: str, payload: dict, runner: Runner) -> None:
    body = json.dumps(payload, ensure_ascii=False)
    _run(["gh", "api", endpoint, "--method", "POST", "--input", "-"], runner, body)


def fetch_pull_request(owner: str, repo: str, number: int, runner: Runner = run_process) -> PullRequest:
    """gh api repos/{o}/{r}/pulls/{n} → head.sha, user.login, html_url."""
    data = json.loads(_run(["gh", "api", f"repos/{owner}/{repo}/pulls/{number}"], runner).stdout)
    return PullRequest(
        owner=owner,
        repo=repo,
        number=number,
        head_sha=data["head"]["sha"],
        author=data["user"]["login"],
        url=data["html_url"],
    )


def fetch_diff(owner: str, repo: str, number: int, runner: Runner = run_process) -> str:
    """gh pr diff {n} -R {o}/{r}."""
    return _run(["gh", "pr", "diff", str(number), "-R", f"{owner}/{repo}"], runner).stdout


def current_user(runner: Runner = run_process) -> str:
    """gh api user → login."""
    return json.loads(_run(["gh", "api", "user"], runner).stdout)["login"]


def download_junit_reports(pr: PullRequest, artifact_name: str, dest_dir: Path,
                           runner: Runner = run_process) -> list[Path]:
    """head SHA의 완료된 최신 workflow run에서 artifact를 dest_dir에 받고, 그 안의 *.xml 경로 목록(재귀, 정렬)을 반환."""
    repo = f"{pr.owner}/{pr.repo}"
    listed = _run(
        ["gh", "run", "list", "-R", repo, "--commit", pr.head_sha,
         "--json", "databaseId,status,conclusion,createdAt"],
        runner,
    )
    completed = [r for r in json.loads(listed.stdout or "[]") if r.get("status") == "completed"]
    if not completed:
        return []  # 테스트 결과가 없어도 리뷰는 진행한다 (R2)
    latest = max(completed, key=lambda r: r.get("createdAt", ""))

    dl = runner(
        ["gh", "run", "download", str(latest["databaseId"]), "-R", repo, "-n", artifact_name, "-D", str(dest_dir)],
        None,
    )
    if dl.returncode != 0:
        return []  # artifact 없음 등 → 결과 없음으로 처리 (R2)
    return sorted(Path(dest_dir).rglob("*.xml"))


def post_review(pr: PullRequest, event: str, body: str, comments: Sequence[InlineComment],
                runner: Runner = run_process) -> None:
    """POST repos/{o}/{r}/pulls/{n}/reviews. JSON 본문은 `gh api ... --method POST --input -`로 stdin 전달."""
    if event not in _ALLOWED_EVENTS:
        raise ValueError(f"event must be one of {_ALLOWED_EVENTS}, got {event!r}")
    payload = {
        "commit_id": pr.head_sha,
        "event": event,
        "body": body,
        "comments": [{"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in comments],
    }
    _post_json(f"repos/{pr.owner}/{pr.repo}/pulls/{pr.number}/reviews", payload, runner)


def post_issue_comment(pr: PullRequest, body: str, runner: Runner = run_process) -> None:
    """POST repos/{o}/{r}/issues/{n}/comments. 본문은 stdin JSON {"body": ...}."""
    _post_json(f"repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments", {"body": body}, runner)
