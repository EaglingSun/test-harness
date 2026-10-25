"""loop/ review · gate · fix · finish 단계. fake runner만 쓴다 — 실제 git/gh 실행 금지 (ADR-004)."""

import json
import subprocess
from pathlib import Path

import pytest

from loop import finish, fix, gate, review
from loop.contract import read_stage, write_stage

SHA = "c" * 40
MERGE_SHA = "9abcdef" + "0" * 33


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class Fake:
    """(prefix → 응답 목록) 표로 답한다. 목록이 하나 남으면 계속 그 응답을 쓴다. 호출 args를 기록한다."""

    def __init__(self, table: dict[tuple[str, ...], list[subprocess.CompletedProcess]]):
        self.table = {k: list(v) for k, v in table.items()}
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(list(args))
        for prefix, answers in self.table.items():
            if self._match(args, prefix):
                return answers.pop(0) if len(answers) > 1 else answers[0]
        raise AssertionError(f"예상하지 못한 명령 {args}")

    @staticmethod
    def _match(args: list[str], prefix: tuple[str, ...]) -> bool:
        if args[0] == "git":
            sub = args[3:]
            while sub and sub[0] == "-c":
                sub = sub[2:]
            return tuple(sub[: len(prefix) - 1]) == prefix[1:]
        return tuple(args[: len(prefix)]) == prefix

    def find(self, *words: str) -> list[list[str]]:
        return [c for c in self.calls if all(w in c for w in words)]


def report_data(stage: str = "test") -> dict:
    return {"stage": stage, "status": "ok", "make_outcome": "failure", "total": 3, "failed": [],
            "unexpected": [], "fixed": [], "missing": [], "head_sha": SHA, "expected_base": [],
            "expected_head": []}


def gate_data(name: str, degraded: bool = False) -> dict:
    return {"stage": f"gate-{name}", "gate": name, "go": True, "decision": "PASS", "reason": "r",
            "forced": False, "degraded": degraded}


# ---- review ----

def test_review_stub_requires_test(tmp_path, capsys):
    assert review.main(["--workspace", str(tmp_path), "--mode", "stub", "--repo", "o/r", "--pr", "1"]) == 1
    assert "test.json" in capsys.readouterr().err


def test_review_stub_writes_contract(tmp_path):
    write_stage(tmp_path / "out", "test", report_data())
    assert review.main(["--workspace", str(tmp_path), "--mode", "stub", "--repo", "o/r", "--pr", "1"]) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["mode"] == "stub" and data["event"] == "COMMENT" and data["posted"] is False
    assert data["counts"] == {"critical": 0, "major": 1, "minor": 1}


# ---- gate ----

@pytest.mark.parametrize("name, upstream", [
    ("autofix", ["test", "review"]),
    ("merge", ["reverify"]),
    ("release", ["merge", "reverify"]),
])
def test_gate_fail_closed_without_upstream(tmp_path, monkeypatch, name, upstream):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    out = tmp_path / "out"
    # 필요한 upstream 중 마지막 하나만 빼고 둔다 → 그래도 exit 1
    present = {
        "test": report_data(), "reverify": report_data("reverify"),
        "review": {"stage": "review", "status": "ok", "mode": "stub", "counts": {}, "critical_by_category": {},
                   "event": "COMMENT", "posted": False, "errors": []},
        "merge": {"stage": "merge", "merged": True, "merge_sha": MERGE_SHA, "noop": False},
    }
    for u in upstream[:-1]:
        write_stage(out, u, present[u])
    no_labels = Fake({("gh", "pr", "view"): [proc(json.dumps({"labels": [], "state": "OPEN"}))]})
    assert gate.main(["--workspace", str(tmp_path), "--gate", name, "--repo", "o/r", "--pr", "7"],
                     runner=no_labels) == 1
    assert not (out / f"gate-{name}.json").exists()


def test_gate_passes_and_writes_output(tmp_path, monkeypatch):
    gh_out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    out = tmp_path / "out"
    write_stage(out, "reverify", report_data("reverify"))
    no_labels = Fake({("gh", "pr", "view"): [proc(json.dumps({"labels": [], "state": "OPEN"}))]})
    assert gate.main(["--workspace", str(tmp_path), "--gate", "merge", "--repo", "o/r", "--pr", "7"],
                     runner=no_labels) == 0
    data = read_stage(out, "gate-merge")
    assert data["go"] is True and data["decision"] == "PASS" and data["forced"] is False
    assert gh_out.read_text(encoding="utf-8") == "go=true\n"


# ---- fix ----

FIX_ARGS = ["--pr", "7", "--head-ref", "feat-x", "--base-ref", "origin/master", "--mode", "stub"]


def fix_fake(log: str = "", over: dict | None = None) -> Fake:
    table = {
        ("git", "log"): [proc(log)],
        ("git", "rev-parse", "--short=7"): [proc("abc1234\n")],
        ("git", "rev-parse", "HEAD"): [proc(SHA + "\n")],
        ("git", "add"): [proc()],
        ("git", "commit"): [proc()],
        ("git", "push"): [proc()],
    }
    table.update(over or {})
    return Fake(table)


def test_fix_noop_when_pr_commit_has_trailer(tmp_path):
    fake = fix_fake(log="chore(loop): stub fix\n\nLoop-Fix: 1\n\nfeat: x\n")
    assert fix.main(["--workspace", str(tmp_path), *FIX_ARGS], runner=fake) == 0
    data = read_stage(tmp_path / "out", "fix")
    assert data["action"] == "NO_ACTION" and data["commit_sha"] == "" and data["attempt"] == 1
    assert fake.calls == [["git", "-C", str(tmp_path), "log", "--format=%B", "origin/master..HEAD"]]


def test_fix_ignores_base_history_trailer(tmp_path):
    """base 이력의 Loop-Fix 커밋은 `origin/master..HEAD` 범위에 나오지 않는다 → 커밋한다."""
    fake = fix_fake()

    def runner(args, input=None):
        if args[3] == "log":
            # 범위를 전체 이력으로 넓히면 base 쪽 트레일러가 보인다.
            fake.calls.append(list(args))
            return proc("" if "origin/master..HEAD" in args else "old fix\n\nLoop-Fix: 1\n")
        return fake(args, input)

    assert fix.main(["--workspace", str(tmp_path), *FIX_ARGS], runner=runner) == 0
    assert read_stage(tmp_path / "out", "fix")["action"] == "COMMITTED"


def test_fix_commits_unique_file_with_trailer(tmp_path):
    fake = fix_fake()
    assert fix.main(["--workspace", str(tmp_path), *FIX_ARGS], runner=fake) == 0
    ws = str(tmp_path)
    rel = ".loop/fix-pr7-abc1234.md"
    assert (tmp_path / rel).read_text(encoding="utf-8").strip()
    assert ["git", "-C", ws, "add", "--", rel] in fake.calls
    commit = fake.find("commit")[0]
    assert commit[:3] == ["git", "-C", ws]
    assert "user.name=loop-bot" in commit and "user.email=loop-bot@users.noreply.github.com" in commit
    assert commit[commit.index("commit"):] == ["commit", "-m", "chore(loop): stub fix for PR #7", "-m", "Loop-Fix: 1"]
    assert ["git", "-C", ws, "push", "origin", "HEAD:feat-x"] in fake.calls
    data = read_stage(tmp_path / "out", "fix")
    assert data["action"] == "COMMITTED" and data["commit_sha"] == SHA and data["status"] == "ok"


def test_fix_git_failure_exit1(tmp_path):
    fake = fix_fake(over={("git", "push"): [proc(code=1, stderr="rejected")]})
    assert fix.main(["--workspace", str(tmp_path), *FIX_ARGS], runner=fake) == 1
    data = read_stage(tmp_path / "out", "fix")
    assert data["status"] == "error" and data["action"] == "FAILED" and "rejected" in data["reason"]


# ---- finish merge ----

FIN = ["--repo", "o/r", "--pr", "7"]
OPEN = proc(json.dumps({"state": "OPEN", "mergeCommit": None}))
MERGED = proc(json.dumps({"state": "MERGED", "mergeCommit": {"oid": MERGE_SHA}}))


def test_merge_requires_reverify(tmp_path):
    fake = Fake({})
    assert finish.main(["merge", "--workspace", str(tmp_path), *FIN], runner=fake) == 1
    assert fake.calls == []


def test_merge_noop_when_already_merged(tmp_path):
    write_stage(tmp_path / "out", "reverify", report_data("reverify"))
    fake = Fake({("gh", "pr", "view"): [MERGED]})
    assert finish.main(["merge", "--workspace", str(tmp_path), *FIN], runner=fake) == 0
    data = read_stage(tmp_path / "out", "merge")
    assert data == {"stage": "merge", "merged": True, "merge_sha": MERGE_SHA, "noop": True}
    assert fake.find("merge", "--merge") == []


def test_merge_uses_match_head_commit(tmp_path):
    write_stage(tmp_path / "out", "reverify", report_data("reverify"))
    fake = Fake({("gh", "pr", "view"): [OPEN, MERGED], ("gh", "pr", "merge"): [proc()]})
    assert finish.main(["merge", "--workspace", str(tmp_path), *FIN], runner=fake) == 0
    assert ["gh", "pr", "merge", "7", "-R", "o/r", "--merge", "--match-head-commit", SHA] in fake.calls
    data = read_stage(tmp_path / "out", "merge")
    assert data["merged"] is True and data["noop"] is False and data["merge_sha"] == MERGE_SHA


def test_merge_failure_exit1(tmp_path):
    write_stage(tmp_path / "out", "reverify", report_data("reverify"))
    fake = Fake({("gh", "pr", "view"): [OPEN], ("gh", "pr", "merge"): [proc(code=1, stderr="head moved")]})
    assert finish.main(["merge", "--workspace", str(tmp_path), *FIN], runner=fake) == 1
    data = read_stage(tmp_path / "out", "merge")
    assert data["merged"] is False and "head moved" in data["reason"]


# ---- finish release ----

def write_merge(out: Path, merged: bool = True) -> None:
    write_stage(out, "merge", {"stage": "merge", "merged": merged, "merge_sha": MERGE_SHA if merged else "",
                               "noop": False})


def test_release_requires_merged(tmp_path):
    write_merge(tmp_path / "out", merged=False)
    fake = Fake({})
    assert finish.main(["release", "--workspace", str(tmp_path), *FIN], runner=fake) == 1
    assert fake.calls == []


def test_release_reuses_existing_tag(tmp_path):
    write_merge(tmp_path / "out")
    fake = Fake({("gh", "release", "view"): [proc(json.dumps({"url": "https://x/rel"}))]})
    assert finish.main(["release", "--workspace", str(tmp_path), *FIN], runner=fake) == 0
    data = read_stage(tmp_path / "out", "release")
    assert data["tag"] == "loop-pr7-9abcdef" and data["reused"] is True and data["url"] == "https://x/rel"
    assert fake.find("create") == []


def test_release_creates_prerelease_at_merge_sha(tmp_path):
    out = tmp_path / "out"
    write_merge(out)
    write_stage(out, "gate-merge", gate_data("merge", degraded=True))
    fake = Fake({("gh", "release", "view"): [proc(code=1, stderr="not found"), proc(json.dumps({"url": "https://x/new"}))],
                 ("gh", "release", "create"): [proc()]})
    assert finish.main(["release", "--workspace", str(tmp_path), *FIN], runner=fake) == 0
    create = fake.find("create")[0]
    assert create[:6] == ["gh", "release", "create", "loop-pr7-9abcdef", "-R", "o/r"]
    assert create[create.index("--target") + 1] == MERGE_SHA
    assert "--prerelease" in create
    notes = Path(create[create.index("--notes-file") + 1])
    assert "degraded" in notes.read_text(encoding="utf-8")
    data = read_stage(out, "release")
    assert data["prerelease"] is True and data["reused"] is False and data["degraded"] is True
    assert data["url"] == "https://x/new"
