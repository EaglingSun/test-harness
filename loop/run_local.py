"""fake runner로 PR 루프 전 단계를 로컬에서 한 바퀴 돈다 (R7). 실제 git/gh/make 는 실행하지 않는다."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from loop import finish, fix, gate, review, test_report
from loop.contract import ContractError, read_stage

REPO = "local/vsm_test"
PR = 1
BASE_REF = "origin/master"
HEAD_REF = "loop-local"
HEAD_SHA = "1234567890abcdef1234567890abcdef12345678"
MERGE_SHA = "fedcba0987654321fedcba0987654321fedcba09"
RELEASE_URL = "https://github.com/local/vsm_test/releases/tag/loop-pr1-fedcba0"


class FakeRunner:
    """명령 인자로 git/gh 호출을 판별해 결정적 응답을 돌려준다. 호출 (args, stdin)을 기록한다."""

    def __init__(self, expected_base: str):
        self.expected_base = expected_base
        self.calls: list[list[str]] = []
        self.pr_views = 0
        self.release_views = 0

    def __call__(self, args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        return self.respond(args)

    def respond(self, args: list[str]) -> subprocess.CompletedProcess:
        def ok(stdout: str = "") -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        if args[0] == "git":
            sub = args[3:]  # git -C <ws> <sub...>
            while sub and sub[0] == "-c":
                sub = sub[2:]
            if sub[0] == "show":
                return ok(self.expected_base)
            if sub[0] == "rev-parse":
                return ok((HEAD_SHA[:7] if "--short=7" in sub else HEAD_SHA) + "\n")
            if sub[0] == "log":
                return ok("")
            if sub[0] in ("add", "commit", "push"):
                return ok()
        if args[0] == "gh":
            if args[1:3] == ["pr", "view"]:
                self.pr_views += 1
                if self.pr_views == 1:
                    return ok(json.dumps({"state": "OPEN", "mergeCommit": None}))
                return ok(json.dumps({"state": "MERGED", "mergeCommit": {"oid": MERGE_SHA}}))
            if args[1:3] == ["pr", "merge"]:
                return ok()
            if args[1:3] == ["release", "view"]:
                self.release_views += 1
                if self.release_views == 1:
                    return subprocess.CompletedProcess(args, 1, stdout="", stderr="release not found")
                return ok(json.dumps({"url": RELEASE_URL}))
            if args[1:3] == ["release", "create"]:
                return ok(RELEASE_URL + "\n")
        return subprocess.CompletedProcess(args, 127, stdout="", stderr=f"FakeRunner: 모르는 명령 {args}")


def prepare_workspace(fixture: Path, ws: Path) -> None:
    (ws / "test-results").mkdir(parents=True, exist_ok=True)
    for xml in sorted((fixture / "test-results").glob("*.xml")):
        shutil.copy2(xml, ws / "test-results" / xml.name)
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture / "tests" / "expected_failures.txt", ws / "tests" / "expected_failures.txt")


def stages(ws: str) -> list[tuple[str, Callable[..., int], list[str]]]:
    common = ["--workspace", ws]
    pr = ["--repo", REPO, "--pr", str(PR)]
    return [
        ("test", test_report.main, [*common, "--stage", "test", "--make-outcome", "failure", "--base-ref", BASE_REF]),
        ("review", review.main, [*common, "--mode", "stub", *pr]),
        ("gate-autofix", gate.main, [*common, "--gate", "autofix"]),
        ("fix", fix.main, [*common, "--pr", str(PR), "--head-ref", HEAD_REF, "--base-ref", BASE_REF,
                           "--mode", "stub"]),
        ("reverify", test_report.main, [*common, "--stage", "reverify", "--make-outcome", "failure",
                                        "--base-ref", BASE_REF]),
        ("gate-merge", gate.main, [*common, "--gate", "merge"]),
        ("merge", finish.main, ["merge", *common, *pr]),
        ("gate-release", gate.main, [*common, "--gate", "release"]),
        ("release", finish.main, ["release", *common, *pr]),
    ]


def summarize(name: str, d: dict) -> str:
    if name in ("test", "reverify"):
        return (f"status={d['status']} total={d['total']} failed={len(d['failed'])} "
                f"unexpected={len(d['unexpected'])} fixed={len(d['fixed'])} missing={len(d['missing'])}")
    if name == "review":
        return f"status={d['status']} mode={d['mode']} event={d['event']} counts={d['counts']}"
    if name.startswith("gate-"):
        return f"go={d['go']} decision={d['decision']}"
    if name == "fix":
        return f"status={d['status']} action={d['action']} commit={d['commit_sha'][:7]}"
    if name == "merge":
        return f"merged={d['merged']} noop={d['noop']} sha={d['merge_sha'][:7]}"
    return f"tag={d['tag']} prerelease={d['prerelease']} reused={d['reused']} url={d['url']}"


def run(fixture: Path, ws: Path) -> int:
    prepare_workspace(fixture, ws)
    runner = FakeRunner((fixture / "expected-base.txt").read_text(encoding="utf-8"))
    out = ws / "out"
    for name, entry, argv in stages(str(ws)):
        code = entry(argv, runner=runner)
        if code != 0:
            print(f"실패: {name} 단계가 exit {code}", file=sys.stderr)
            return 1
    try:
        lines = [f"{name:<13} {summarize(name, read_stage(out, name))}" for name, _, _ in stages(str(ws))]
    except ContractError as e:
        print(f"실패: 계약 확인 — {e}", file=sys.stderr)
        return 1
    print("\n".join(["", "== loop run_local =="] + lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass  # Windows 콘솔 인코딩 재설정 실패는 무시한다
    p = argparse.ArgumentParser(prog="loop.run_local", description="fake runner로 루프 전 단계를 한 바퀴 돈다")
    p.add_argument("--fixture", required=True, type=Path)
    p.add_argument("--out", type=Path, help="workspace 폴더 (기본: 임시 폴더, 끝나면 삭제)")
    args = p.parse_args(argv)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        return run(args.fixture, args.out)
    with tempfile.TemporaryDirectory() as tmp:
        return run(args.fixture, Path(tmp))


if __name__ == "__main__":
    sys.exit(main())
