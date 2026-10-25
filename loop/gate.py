"""autofix · merge · release 게이트. 1차 무게이트: upstream 계약만 확인하고 항상 통과한다 (ADR-006)."""

import argparse
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
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    out = Path(args.workspace) / "out"
    try:
        for name in UPSTREAM[args.gate]:
            read_stage(out, name)  # 없거나 깨졌으면 fail-closed
        result = {"stage": f"gate-{args.gate}", "gate": args.gate, "go": True, "decision": "PASS",
                  "reason": "무게이트(1차 뼈대)", "forced": False, "degraded": False}
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
