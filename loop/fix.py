"""fix 단계: stub(고유 파일 커밋 + Loop-Fix 트레일러). Fix 상한 1회 — PR 고유 커밋만 센다 (ADR-006)."""

import argparse
import sys
from pathlib import Path

from loop.contract import ContractError, write_stage
from pr_reviewer.proc import Runner, run_process

TRAILER = "Loop-Fix:"
BOT_NAME = "loop-bot"
BOT_EMAIL = "loop-bot@users.noreply.github.com"


class GitError(Exception):
    pass


def _git(runner: Runner, workspace: str, *args: str) -> str:
    r = runner(["git", "-C", workspace, *args], None)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)} 실패: {(r.stderr or '').strip()}")
    return r.stdout or ""


def already_fixed(log_text: str) -> bool:
    return any(line.strip().startswith(TRAILER) for line in log_text.splitlines())


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.fix", description="루프 수정 단계 (stub)")
    p.add_argument("--workspace", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--head-ref", required=True)
    p.add_argument("--base-ref", required=True)
    p.add_argument("--mode", choices=("stub",), default="stub")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    ws = str(args.workspace)
    out = Path(ws) / "out"
    data = {"stage": "fix", "status": "ok", "mode": args.mode, "action": "", "commit_sha": "", "attempt": 1}
    code = 0
    try:
        # base 이력은 세지 않는다: PR 고유 커밋(<base-ref>..HEAD)만 본다.
        if already_fixed(_git(runner, ws, "log", "--format=%B", f"{args.base_ref}..HEAD")):
            data["action"] = "NO_ACTION"
            data["reason"] = "Fix 상한(1회) 도달: PR 고유 커밋에 Loop-Fix 트레일러가 있다"
        else:
            head7 = _git(runner, ws, "rev-parse", "--short=7", "HEAD").strip()
            rel = f".loop/fix-pr{args.pr}-{head7}.md"
            target = Path(ws) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"stub fix for PR #{args.pr} at {head7} (loop 1차 뼈대: 실제 수정 없음)\n",
                              encoding="utf-8")
            _git(runner, ws, "add", "--", rel)
            _git(runner, ws, "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
                 "commit", "-m", f"chore(loop): stub fix for PR #{args.pr}", "-m", f"{TRAILER} 1")
            _git(runner, ws, "push", "origin", f"HEAD:{args.head_ref}")
            data["commit_sha"] = _git(runner, ws, "rev-parse", "HEAD").strip()
            data["action"] = "COMMITTED"
    except (GitError, OSError) as e:
        data.update(status="error", action="FAILED", reason=str(e))
        print(f"fix: {e}", file=sys.stderr)
        code = 1
    try:
        write_stage(out, "fix", data)
    except (ContractError, OSError) as e:
        print(f"fix: 계약 파일을 쓰지 못했다 — {e}", file=sys.stderr)
        return 1
    print(f"fix: {data['action']} {data['commit_sha']}".rstrip())
    return code


if __name__ == "__main__":
    sys.exit(main())
