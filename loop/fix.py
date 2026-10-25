"""fix 단계: stub(고유 파일 커밋 + Loop-Fix 트레일러) · real(claude 편집, ADR-007).

Fix 상한 1회 — PR 고유 커밋만 센다 (ADR-006).
"""

import argparse
import functools
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from loop.contract import ContractError, read_stage, write_stage
from pr_reviewer.proc import Runner, run_process

TRAILER = "Loop-Fix:"
BOT_NAME = "loop-bot"
BOT_EMAIL = "loop-bot@users.noreply.github.com"
CLAUDE_TIMEOUT = 600
RAW_LIMIT = 2000
ALLOWED_PREFIXES = ("src/", "include/")
REQUIREMENTS_PATH = "test_ref/요구사항.md"
CLAUDE_ARGS = ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
               "--allowedTools", "Read", "Edit", "Glob", "Grep", "--disallowedTools", "Bash", "Write"]
INSTRUCTION = ("`src/`·`include/` 아래 파일만 최소한으로 고쳐 위 테스트가 요구사항대로 통과하게 하라. "
               "테스트(`tests/`)·`tests/expected_failures.txt`·그 밖 파일은 고치지 마라. 빌드·실행은 하지 마라.")


class GitError(Exception):
    pass


def _git(runner: Runner, workspace: str, *args: str) -> str:
    r = runner(["git", "-C", workspace, *args], None)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)} 실패: {(r.stderr or '').strip()}")
    return r.stdout or ""


def already_fixed(log_text: str) -> bool:
    return any(line.strip().startswith(TRAILER) for line in log_text.splitlines())


class FixError(Exception):
    """실패 정보 조립 실패 · claude 실패 · 허용 밖 변경."""


def failure_messages(out: Path, ids: list[str]) -> dict[str, str]:
    """`out/*.xml`(loop-junit artifact) 에서 ids 케이스의 `<failure|error message>` → {식별자: 메시지}.

    식별자는 test_report 와 같은 `<testsuite name>::<testcase name>` 이다.
    """
    wanted = set(ids)
    found: dict[str, str] = {}
    for path in sorted(Path(out).glob("*.xml")):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as e:
            raise FixError(f"{path}: XML 을 읽지 못했다 — {e}") from e
        for ts in root.iter("testsuite"):
            for tc in ts.iter("testcase"):
                key = f"{ts.get('name')}::{tc.get('name')}"
                if key not in wanted:
                    continue
                for kind in ("failure", "error"):
                    elem = tc.find(kind)
                    if elem is not None:
                        found[key] = elem.get("message") or (elem.text or "").strip()
                        break
    return found


def build_prompt(workspace: Path) -> str:
    """unexpected 식별자 · failure message · 요구사항 본문 · 지시를 코드로 조립한다."""
    out = workspace / "out"
    try:
        unexpected = read_stage(out, "test")["unexpected"]
        requirements = (workspace / REQUIREMENTS_PATH).read_text(encoding="utf-8")
    except (ContractError, OSError) as e:
        raise FixError(f"실패 정보를 모으지 못했다 — {e}") from e
    if not unexpected:
        raise FixError("out/test.json 에 unexpected 실패가 없다")
    messages = failure_messages(out, unexpected)
    lines = ["# 실패한 테스트 (기준 목록에 없는 실패)"]
    lines += [f"- {i}: {messages.get(i, '(메시지 없음)')}" for i in unexpected]
    lines += ["", f"# 요구사항 ({REQUIREMENTS_PATH})", requirements.strip(), "", "# 지시", INSTRUCTION, ""]
    return "\n".join(lines)


def _raw_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _write_raw(out: Path, stdout, stderr) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "fix-claude-raw.txt").write_text(
        f"--- stdout ---\n{_raw_text(stdout)[:RAW_LIMIT]}\n--- stderr ---\n{_raw_text(stderr)[:RAW_LIMIT]}\n",
        encoding="utf-8")


def changed_paths(porcelain: str) -> list[str]:
    """`git status --porcelain` → 바뀐 경로(이름 바꿈은 옛 경로·새 경로 둘 다). git 이 감싼 따옴표는 벗긴다."""
    paths: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        for part in line[3:].split(" -> "):
            part = part.strip()
            if len(part) >= 2 and part.startswith('"') and part.endswith('"'):
                part = part[1:-1]
            if part and part not in paths:
                paths.append(part)
    return paths


def _run_real(runner: Runner, claude_runner: Runner, ws: str, args: argparse.Namespace, data: dict) -> int:
    out = Path(ws) / "out"
    prompt = build_prompt(Path(ws))
    try:
        r = claude_runner(CLAUDE_ARGS, prompt)
    except subprocess.TimeoutExpired as e:
        _write_raw(out, e.stdout, e.stderr)
        raise FixError(f"claude 가 {CLAUDE_TIMEOUT}초 안에 끝나지 않았다") from e
    if r.returncode != 0:
        _write_raw(out, r.stdout, r.stderr)
        raise FixError(f"claude 비정상 종료(exit {r.returncode})")
    changed = changed_paths(_git(runner, ws, "status", "--porcelain"))
    data["changed_files"] = changed
    if not changed:
        data["action"] = "NO_ACTION"
        data["reason"] = "Fix 가 변경하지 않음"
        return 0
    outside = [p for p in changed if not p.startswith(ALLOWED_PREFIXES)]
    if outside:
        _git(runner, ws, "checkout", "--", ".")
        _git(runner, ws, "clean", "-fd", "--", ".")
        raise FixError(f"허용 밖 경로를 바꿔 되돌렸다: {', '.join(outside)}")
    _git(runner, ws, "add", "--", *changed)
    _git(runner, ws, "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-m", f"fix(loop): auto-fix for PR #{args.pr}", "-m", f"{TRAILER} 1")
    _git(runner, ws, "push", "origin", f"HEAD:{args.head_ref}")
    data["commit_sha"] = _git(runner, ws, "rev-parse", "HEAD").strip()
    data["action"] = "COMMITTED"
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="loop.fix", description="루프 수정 단계 (stub · real)")
    p.add_argument("--workspace", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--head-ref", required=True)
    p.add_argument("--base-ref", required=True)
    p.add_argument("--mode", choices=("stub", "real"), default="stub")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = run_process,
         claude_runner: Runner | None = None) -> int:
    args = _parse_args(argv)
    ws = str(args.workspace)
    if claude_runner is None:
        claude_runner = functools.partial(run_process, cwd=ws, timeout=CLAUDE_TIMEOUT)
    out = Path(ws) / "out"
    data = {"stage": "fix", "status": "ok", "mode": args.mode, "action": "", "commit_sha": "", "attempt": 1}
    code = 0
    try:
        # base 이력은 세지 않는다: PR 고유 커밋(<base-ref>..HEAD)만 본다.
        if already_fixed(_git(runner, ws, "log", "--format=%B", f"{args.base_ref}..HEAD")):
            data["action"] = "NO_ACTION"
            data["reason"] = "Fix 상한(1회) 도달: PR 고유 커밋에 Loop-Fix 트레일러가 있다"
        elif args.mode == "real":
            _run_real(runner, claude_runner, ws, args, data)
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
    except (GitError, FixError, OSError) as e:
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
