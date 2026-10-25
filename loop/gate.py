"""autofix · merge · release 게이트. 1차 임시 기준(ADR-007, R12)으로 판정하고, 실행 시점 PR 라벨
`force-block-<게이트>` 가 있으면 기준보다 먼저 강제로 막는다 (ADR-006, R11)."""

import argparse
import json
import sys
from pathlib import Path

from loop.contract import ContractError, read_stage, write_github_output, write_stage
from pr_reviewer.proc import Runner, run_process

UPSTREAM: dict[str, tuple[str, ...]] = {
    "autofix": ("test", "review"),
    "merge": ("reverify", "review"),
    "release": ("merge", "reverify", "gate-merge"),
}
AUTOFIX_MAX = 3  # unexpected 이 이 건수 이하면 AUTO_FIX (1차 임시 기준)
DEGRADED_NOTE = "리뷰 실패 — 리뷰 없이 판정"
PARTIAL_NOTE = "리뷰 부분 실패 {n}건"  # status ok + errors 1건 이상 (R14) — 표시만, 판정은 그대로


def decide_autofix(test: dict) -> tuple[bool, str, str]:
    """test 계약 → (go, decision, reason). 위에서부터 처음 맞는 기준."""
    if test["status"] == "error":
        return False, "NEEDS_INVESTIGATION", "판정 불가 — test error"
    n = len(test["unexpected"])
    if n == 0:
        return False, "NO_ACTION", "unexpected 0건"
    if n <= AUTOFIX_MAX:
        return True, "AUTO_FIX", f"unexpected {n}건 (≤ {AUTOFIX_MAX})"
    return False, "NEEDS_HUMAN", f"unexpected {n}건 (> {AUTOFIX_MAX})"


def _reverify_verdict(reverify: dict) -> tuple[bool, str]:
    """merge 기준의 reverify 판정. merge · release 게이트가 같이 쓴다."""
    if reverify["status"] == "error":
        return False, "판정 불가 — reverify error"
    if reverify["unexpected"] or reverify["missing"]:
        parts = [f"{k} {len(reverify[k])}건 {reverify[k]}" for k in ("unexpected", "missing") if reverify[k]]
        return False, " · ".join(parts)
    stale = [i for i in reverify["fixed"] if i in reverify["expected_head"]]
    if stale:
        return False, f"목록 갱신 필요(사람 몫) — fixed 가 head 목록에 남음 {stale}"
    return True, "reverify 통과"


def decide_merge(reverify: dict, review: dict) -> tuple[bool, str, str, bool]:
    """reverify · review 계약 → (go, decision, reason, degraded). 리뷰 critical 은 막지 않는다."""
    go, reason = _reverify_verdict(reverify)
    counts = review.get("counts")
    critical = counts.get("critical", 0) if isinstance(counts, dict) else 0
    if critical:
        reason += f" · 리뷰 critical {critical}건(정적 추정 — 막지 않음)"
    degraded = review["status"] == "error"
    if degraded:
        reason += f" · {DEGRADED_NOTE}"
    elif review["errors"]:
        degraded = True
        reason += f" · {PARTIAL_NOTE.format(n=len(review['errors']))}"
    return go, "PASS" if go else "BLOCK", reason, degraded


def decide_release(merge: dict, reverify: dict, gate_merge: dict) -> tuple[bool, str, str, bool]:
    """merge · reverify · gate-merge 계약 → (go, decision, reason, degraded). degraded 는 gate-merge 것을 옮긴다."""
    degraded = gate_merge["degraded"]
    if not merge["merged"]:
        return False, "BLOCK", "머지되지 않았다", degraded
    go, reason = _reverify_verdict(reverify)
    return go, "PASS" if go else "BLOCK", reason, degraded


def decide(name: str, up: dict[str, dict]) -> tuple[bool, str, str, bool]:
    if name == "autofix":
        return (*decide_autofix(up["test"]), False)
    if name == "merge":
        return decide_merge(up["reverify"], up["review"])
    return decide_release(up["merge"], up["reverify"], up["gate-merge"])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.gate", description="루프 게이트 (1차 임시 기준)")
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
        up = {name: read_stage(out, name) for name in UPSTREAM[args.gate]}  # 없거나 깨졌으면 fail-closed
        labels, state = read_labels(runner, args.repo, args.pr)
        go, decision, reason, degraded = decide(args.gate, up)
        switch = f"force-block-{args.gate}"
        forced = switch in labels
        if forced:  # 강제 스위치가 기준보다 먼저
            go, decision, reason = False, "BLOCK", f"강제 스위치 {switch}"
        result = {"stage": f"gate-{args.gate}", "gate": args.gate, "go": go, "decision": decision,
                  "reason": reason, "forced": forced, "degraded": degraded, "labels": labels, "pr_state": state}
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
