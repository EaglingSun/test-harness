"""CLI 진입점 + 파이프라인 조립 (R6, R5, ADR-001, ADR-003, ADR-004)."""

import argparse
import dataclasses
import json
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from pr_reviewer.agents import run_all_agents
from pr_reviewer.aggregate import build_review_plan
from pr_reviewer.diff import parse_commentable_lines
from pr_reviewer.github import (
    GhError,
    current_user,
    download_junit_reports,
    fetch_diff,
    fetch_pull_request,
    post_issue_comment,
    post_review,
)
from pr_reviewer.junit import JUnitParseError, parse_junit_files
from pr_reviewer.models import AgentResult, PullRequest, ReviewPlan, TestReport
from pr_reviewer.proc import Runner, run_process

DEFAULT_JUNIT_ARTIFACT = "junit-results"


def _repo(value: str) -> tuple[str, str]:
    owner, sep, repo = value.partition("/")
    if not sep or not owner or not repo or "/" in repo:
        raise argparse.ArgumentTypeError(f"owner/repo 형식이어야 한다: {value!r}")
    return owner, repo


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pr_reviewer",
        description="GitHub PR 한 건을 3개 관점(구조 기반 테스트/보안/코드 리뷰)으로 리뷰하고 게시한다.",
    )
    parser.add_argument("repo", type=_repo, help="대상 저장소 (owner/repo)")
    parser.add_argument("number", type=int, help="PR 번호")
    parser.add_argument("--dry-run", action="store_true", help="게시하지 않고 payload JSON을 출력한다")
    parser.add_argument("--junit-artifact", default=DEFAULT_JUNIT_ARTIFACT,
                        help=f"JUnit XML artifact 이름 (기본 {DEFAULT_JUNIT_ARTIFACT})")
    parser.add_argument("--junit-dir", type=Path, default=None,
                        help="artifact 다운로드 대신 이 디렉터리의 *.xml을 읽는다 (--junit-artifact보다 우선)")
    parser.add_argument("--plan-out", type=Path, default=None,
                        help="리뷰 계획 payload JSON을 게시 전에 이 경로에 저장한다")
    parser.add_argument("--current-user", default=None,
                        help="현재 사용자 login (주면 gh api user를 호출하지 않는다)")
    return parser.parse_args(argv)


def _parse_report(paths: Sequence[Path]) -> TestReport | None:
    try:
        return parse_junit_files(paths)
    except JUnitParseError as e:
        print(f"경고: JUnit XML 파싱 실패, 테스트 결과 없이 진행한다: {e}", file=sys.stderr)
        return None


def _load_report(pr: PullRequest, artifact: str, runner: Runner) -> TestReport | None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = download_junit_reports(pr, artifact, Path(tmp), runner)
        if not paths:
            return None
        return _parse_report(paths)


def _load_local_report(junit_dir: Path) -> TestReport | None:
    paths = sorted(junit_dir.glob("*.xml"))
    if not paths:
        print(f"경고: --junit-dir 에 JUnit XML 이 없다: {junit_dir}", file=sys.stderr)
        return None
    return _parse_report(paths)


def _dry_run_payload(plan: ReviewPlan, results: Sequence[AgentResult]) -> dict:
    return {
        "event": plan.event,
        "review_body": plan.review_body,
        "inline": [dataclasses.asdict(c) for c in plan.inline],
        "summary_markdown": plan.summary_markdown,
        "agents": [
            {"category": r.category, "findings": [dataclasses.asdict(f) for f in r.findings],
             "error": r.error, "skipped_reason": r.skipped_reason}
            for r in results
        ],
    }


def main(argv: Sequence[str] | None = None, runner: Runner = run_process) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass  # Windows 콘솔 인코딩 재설정 실패는 무시한다

    args = _parse_args(argv)
    owner, repo = args.repo

    try:
        pr = fetch_pull_request(owner, repo, args.number, runner)
        diff = fetch_diff(owner, repo, args.number, runner)
        user = args.current_user if args.current_user is not None else current_user(runner)
    except GhError as e:
        print(f"PR 조회 실패: {e}", file=sys.stderr)
        return 1
    commentable = parse_commentable_lines(diff)

    if args.junit_dir is not None:
        report = _load_local_report(args.junit_dir)
    else:
        report = _load_report(pr, args.junit_artifact, runner)
    results = run_all_agents(pr, diff, report, runner)
    plan = build_review_plan(pr, results, commentable, user, report)

    payload = json.dumps(_dry_run_payload(plan, results), ensure_ascii=False, indent=2)
    if args.plan_out is not None:
        # 게시 전에 쓴다 — 게시가 실패해도 계획 파일은 남는다.
        args.plan_out.write_text(payload, encoding="utf-8")

    if args.dry_run:
        print(payload)
        return 0

    try:
        post_review(pr, plan.event, plan.review_body, plan.inline, runner)
    except GhError as e:
        # 최소한 요약 결과는 PR에 남긴다.
        post_issue_comment(pr, f"{plan.summary_markdown}\n인라인 리뷰 게시 실패: {e}\n", runner)
        return 1
    post_issue_comment(pr, plan.summary_markdown, runner)
    print(f"{pr.url} event={plan.event} inline={len(plan.inline)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
