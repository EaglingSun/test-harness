"""review 단계: stub(고정 findings). real 모드는 다음 step 에서 붙인다 (R7, R10)."""

import argparse
import sys
from pathlib import Path

from loop.contract import ContractError, read_stage, write_stage
from pr_reviewer.proc import Runner, run_process


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.review", description="PR 리뷰 단계")
    p.add_argument("--workspace", required=True)
    p.add_argument("--mode", choices=("stub",), default="stub")
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    out = Path(args.workspace) / "out"
    try:
        read_stage(out, "test")  # upstream 계약 체인 확인
        write_stage(out, "review", {
            "stage": "review", "status": "ok", "mode": "stub",
            "counts": {"critical": 0, "major": 1, "minor": 1},
            "critical_by_category": {}, "event": "COMMENT", "posted": False, "errors": [],
        })
    except (ContractError, OSError) as e:
        print(f"review: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
