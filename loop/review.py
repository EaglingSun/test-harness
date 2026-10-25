"""review 단계: stub(고정 findings) / real(pr_reviewer 실행 → review 계약 변환) (R7, R10)."""

import argparse
import json
import sys
from pathlib import Path

from loop.contract import ContractError, read_stage, write_stage
from pr_reviewer.proc import Runner, run_process

DEFAULT_CURRENT_USER = "github-actions[bot]"  # GITHUB_TOKEN 으로 게시하므로 (ADR-006)
SEVERITIES = ("critical", "major", "minor")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.review", description="PR 리뷰 단계")
    p.add_argument("--workspace", required=True)
    p.add_argument("--mode", choices=("stub", "real"), default="stub")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--current-user", default=DEFAULT_CURRENT_USER)
    return p.parse_args(argv)


def _stub() -> dict:
    return {
        "stage": "review", "status": "ok", "mode": "stub",
        "counts": {"critical": 0, "major": 1, "minor": 1},
        "critical_by_category": {}, "event": "COMMENT", "posted": False, "errors": [],
    }


def _last_line(text: str | None) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def _load_plan(path: Path) -> tuple[dict | None, str | None]:
    """plan JSON 을 읽는다. 실패하면 (None, 사유)."""
    if not path.is_file():
        return None, f"plan 파일이 없다: {path}"
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return None, f"plan JSON 을 읽지 못했다: {e}"
    if not isinstance(plan, dict) or not isinstance(plan.get("agents"), list):
        return None, "plan 형식 오류: agents 목록이 없다"
    return plan, None


def _real(args: argparse.Namespace, out: Path, runner: Runner) -> dict:
    plan_path = out / "review-plan.json"
    cmd = [sys.executable, "-m", "pr_reviewer", args.repo, str(args.pr),
           "--junit-dir", str(out), "--plan-out", str(plan_path),
           "--current-user", args.current_user]
    proc = runner(cmd, None)

    # counts: 에이전트 원천 등급(ADR-005 강등·병합 집계 전) — counts_basis 로 밝힌다.
    counts = {s: 0 for s in SEVERITIES}
    critical_by_category: dict[str, int] = {}
    errors: list[str] = []
    event = None

    plan, plan_error = _load_plan(plan_path)
    if plan is not None:
        event = plan.get("event")
        for agent in plan["agents"]:
            if agent.get("error") is not None:
                errors.append(str(agent["error"]))
            for f in agent.get("findings") or []:
                sev = f.get("severity")
                if sev in counts:
                    counts[sev] += 1
                if sev == "critical":
                    cat = str(f.get("category"))
                    critical_by_category[cat] = critical_by_category.get(cat, 0) + 1
    else:
        errors.append(plan_error)

    ok = proc.returncode == 0 and plan is not None
    if proc.returncode != 0:
        errors.append(f"pr_reviewer exit {proc.returncode}: {_last_line(proc.stderr)}")
    return {
        "stage": "review", "status": "ok" if ok else "error", "mode": "real",
        "counts": counts,  # 원천 등급 · 집계 전
        "counts_basis": "agent_raw",
        "critical_by_category": critical_by_category, "event": event,
        "posted": ok, "errors": errors,
    }


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    out = Path(args.workspace) / "out"
    try:
        read_stage(out, "test")  # upstream 계약 체인 확인
        # real 이 실패해도 status error 계약을 쓰고 exit 0 — 판정은 게이트 몫.
        data = _real(args, out, runner) if args.mode == "real" else _stub()
        write_stage(out, "review", data)
    except (ContractError, OSError) as e:
        print(f"review: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
