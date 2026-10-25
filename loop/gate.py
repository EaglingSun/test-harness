"""autofix · merge · release 게이트. 기준은 무게이트(항상 통과)이고, 실행 시점 PR 라벨
`force-block-<게이트>` 가 있을 때만 강제로 막는다 (ADR-006, R11)."""

import argparse
import json
import sys
from pathlib import Path

from loop.contract import ContractError, read_stage, write_github_output, write_stage
from pr_reviewer.proc import Runner, run_process

UPSTREAM: dict[str, tuple[str, ...]] = {
    "autofix": ("test", "review"),
    "merge": ("reverify",),
    "release": ("merge", "reverify"),
}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.gate", description="루프 게이트 (1차 무게이트)")
    p.add_argument("--workspace", required=True)
    p.add_argument("--gate", choices=tuple(UPSTREAM), required=True)
    p.add_argument("--repo", required=True, help="OWNER/REPO")
    p.add_argument("--pr", required=True, type=int)
    return p.parse_args(argv)


def read_labels(runner: Runner, repo: str, pr: int) -> tuple[list[str], str]:
    """실행 시점 PR 라벨 이름 목록과 state 를 읽는다. 실패하면 ContractError (fail-closed)."""
    proc = runner(["gh", "pr", "view", str(pr), "-R", repo, "--json", "labels,state"], None)
    if proc.returncode != 0:
        raise ContractError(f"gh pr view 실패(exit {proc.returncode}): {(proc.stderr or '').strip()}")
    try:
        data = json.loads(proc.stdout)
        labels = [label["name"] for label in data["labels"]]
        state = data["state"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ContractError(f"gh pr view 응답을 읽지 못했다 — {e!r}") from e
    if not all(isinstance(n, str) for n in labels) or not isinstance(state, str):
        raise ContractError("gh pr view 응답의 labels/state 타입이 어긋난다")
    return labels, state


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    out = Path(args.workspace) / "out"
    try:
        for name in UPSTREAM[args.gate]:
            read_stage(out, name)  # 없거나 깨졌으면 fail-closed
        labels, state = read_labels(runner, args.repo, args.pr)
        switch = f"force-block-{args.gate}"
        forced = switch in labels
        result = {"stage": f"gate-{args.gate}", "gate": args.gate, "go": not forced,
                  "decision": "BLOCK" if forced else "PASS",
                  "reason": f"강제 스위치 {switch}" if forced else "무게이트(1차 뼈대)",
                  "forced": forced, "degraded": False, "labels": labels, "pr_state": state}
        write_stage(out, result["stage"], result)
    except (ContractError, OSError) as e:
        print(f"gate-{args.gate}: {e}", file=sys.stderr)
        return 1
    write_github_output("go", "true" if result["go"] else "false")
    print(f"gate-{args.gate}: {result['decision']} — {result['reason']}")
    # autofix 게이트는 다음 job 의 if 조건(go)으로 막으므로 항상 0. merge · release 는 go false 면 빨간 체크.
    if args.gate != "autofix" and not result["go"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
