"""merge · release 단계 (gh, 멱등). 이미 머지됐거나 태그가 있으면 다시 만들지 않는다 (ADR-006)."""

import argparse
import json
import sys
from pathlib import Path

from loop.contract import ContractError, read_stage, write_stage
from pr_reviewer.proc import Runner, run_process

GATE_STAGES = ("gate-autofix", "gate-merge", "gate-release")
NOTE_STAGES = ("test", "review", "gate-autofix", "fix", "reverify", "gate-merge", "merge", "gate-release")


class GhError(Exception):
    pass


def _gh(runner: Runner, *args: str) -> str:
    r = runner(["gh", *args], None)
    if r.returncode != 0:
        raise GhError(f"gh {' '.join(args)} 실패: {(r.stderr or '').strip()}")
    return r.stdout or ""


def _json(text: str, what: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise GhError(f"{what} 출력이 JSON 이 아니다: {e}") from e
    if not isinstance(data, dict):
        raise GhError(f"{what} 출력이 JSON 객체가 아니다")
    return data


def _pr_view(runner: Runner, repo: str, pr: int) -> dict:
    return _json(_gh(runner, "pr", "view", str(pr), "-R", repo, "--json", "state,mergeCommit"), "gh pr view")


def _merge_sha(view: dict) -> str:
    return (view.get("mergeCommit") or {}).get("oid") or ""


def do_merge(out: Path, repo: str, pr: int, runner: Runner) -> int:
    head_sha = read_stage(out, "reverify")["head_sha"]
    data = {"stage": "merge", "merged": False, "merge_sha": "", "noop": False}
    code = 0
    try:
        view = _pr_view(runner, repo, pr)
        if view.get("state") == "MERGED":
            data.update(merged=True, noop=True, merge_sha=_merge_sha(view))
        else:
            _gh(runner, "pr", "merge", str(pr), "-R", repo, "--merge", "--match-head-commit", head_sha)
            view = _pr_view(runner, repo, pr)
            if view.get("state") != "MERGED":
                raise GhError(f"머지 후 상태가 MERGED 가 아니다: {view.get('state')!r}")
            data.update(merged=True, merge_sha=_merge_sha(view))
    except GhError as e:
        data.update(merged=False, merge_sha="", noop=False, reason=str(e))
        print(f"merge: {e}", file=sys.stderr)
        code = 1
    write_stage(out, "merge", data)
    print(f"merge: merged={data['merged']} noop={data['noop']} {data['merge_sha']}".rstrip())
    return code


def release_notes(out: Path, pr: int, degraded: bool) -> str:
    """각 단계 계약의 status/decision 요약. degraded 가 하나라도 true 면 표시한다."""
    lines = [f"# loop PR #{pr}", ""]
    if degraded:
        lines += ["> degraded: 게이트 중 하나 이상이 기준을 완화해 통과했다.", ""]
    for name in NOTE_STAGES:
        if not (out / f"{name}.json").is_file():
            lines.append(f"- {name}: (계약 없음)")
            continue
        d = read_stage(out, name)
        if "decision" in d:
            state = d["decision"]
        elif "status" in d:
            state = d["status"]
        else:
            state = "merged" if d.get("merged") else "not merged"
        lines.append(f"- {name}: {state}")
    return "\n".join(lines) + "\n"


def do_release(out: Path, repo: str, pr: int, runner: Runner) -> int:
    merge = read_stage(out, "merge")
    if not merge["merged"] or not merge["merge_sha"]:
        raise ContractError("merge.json: 머지되지 않아 릴리스할 수 없다")
    degraded = any(read_stage(out, g)["degraded"] for g in GATE_STAGES if (out / f"{g}.json").is_file())
    tag = f"loop-pr{pr}-{merge['merge_sha'][:7]}"
    data = {"stage": "release", "tag": tag, "url": "", "prerelease": True, "reused": False, "degraded": degraded}
    code = 0
    try:
        existing = runner(["gh", "release", "view", tag, "-R", repo, "--json", "url"], None)
        if existing.returncode == 0:
            data.update(reused=True, url=_json(existing.stdout or "", "gh release view").get("url", ""))
        else:
            notes = out / "release-notes.md"
            notes.write_text(release_notes(out, pr, degraded), encoding="utf-8")
            _gh(runner, "release", "create", tag, "-R", repo, "--target", merge["merge_sha"], "--prerelease",
                "--title", f"loop PR #{pr}", "--notes-file", str(notes))
            view = _json(_gh(runner, "release", "view", tag, "-R", repo, "--json", "url"), "gh release view")
            data["url"] = view.get("url", "")
    except GhError as e:
        data["reason"] = str(e)
        print(f"release: {e}", file=sys.stderr)
        code = 1
    write_stage(out, "release", data)
    print(f"release: {tag} reused={data['reused']} {data['url']}".rstrip())
    return code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.finish", description="루프 merge · release 단계")
    p.add_argument("action", choices=("merge", "release"))
    p.add_argument("--workspace", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", type=int, required=True)
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process) -> int:
    args = _parse_args(argv)
    out = Path(args.workspace) / "out"
    try:
        out.mkdir(parents=True, exist_ok=True)
        if args.action == "merge":
            return do_merge(out, args.repo, args.pr, runner)
        return do_release(out, args.repo, args.pr, runner)
    except (ContractError, OSError) as e:
        print(f"{args.action}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
