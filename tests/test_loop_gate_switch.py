"""loop/gate.py 강제 스위치 (R11). 실행 시점 PR 라벨 force-block-<게이트>. fake runner만 쓴다 (ADR-004)."""

import json
import subprocess

import pytest

from loop import gate
from loop.contract import read_stage, write_stage

SHA = "c" * 40
REPO = "o/r"
PR = "7"
GATES = ("autofix", "merge", "release")


def proc(stdout: str = "", code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class Fake:
    """gh pr view 응답 하나를 돌려준다. 다른 명령은 실패로 본다. 호출 args를 기록한다."""

    def __init__(self, response: subprocess.CompletedProcess):
        self.response = response
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(list(args))
        if args[:3] != ["gh", "pr", "view"]:
            raise AssertionError(f"예상하지 못한 명령 {args}")
        return self.response


def labels_view(*names: str, state: str = "OPEN") -> Fake:
    return Fake(proc(json.dumps({"labels": [{"name": n} for n in names], "state": state})))


def report_data(stage: str) -> dict:
    return {"stage": stage, "status": "ok", "make_outcome": "failure", "total": 3, "failed": [],
            "unexpected": [], "fixed": [], "missing": [], "head_sha": SHA, "expected_base": [],
            "expected_head": []}


UPSTREAM_DATA = {
    "test": report_data("test"),
    "reverify": report_data("reverify"),
    "review": {"stage": "review", "status": "ok", "mode": "stub", "counts": {}, "critical_by_category": {},
               "event": "COMMENT", "posted": False, "errors": []},
    "merge": {"stage": "merge", "merged": True, "merge_sha": "9" * 40, "noop": False},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """모든 upstream 계약을 둔 workspace. GITHUB_OUTPUT 은 tmp 파일."""
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_out"))
    for name, data in UPSTREAM_DATA.items():
        write_stage(tmp_path / "out", name, data)
    return tmp_path


def run_gate(ws, name: str, runner) -> int:
    return gate.main(["--workspace", str(ws), "--gate", name, "--repo", REPO, "--pr", PR], runner=runner)


def gh_output(ws) -> str:
    return (ws / "gh_out").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", GATES)
def test_no_label_passes(ws, name):
    assert run_gate(ws, name, labels_view("bug")) == 0
    data = read_stage(ws / "out", f"gate-{name}")
    assert data["go"] is True and data["decision"] == "PASS" and data["forced"] is False
    assert data["reason"] == "무게이트(1차 뼈대)"
    assert gh_output(ws) == "go=true\n"


@pytest.mark.parametrize("name", GATES)
def test_own_label_blocks(ws, name):
    code = run_gate(ws, name, labels_view("bug", f"force-block-{name}"))
    assert code == (0 if name == "autofix" else 1)
    data = read_stage(ws / "out", f"gate-{name}")
    assert data["go"] is False and data["decision"] == "BLOCK" and data["forced"] is True
    assert data["reason"] == f"강제 스위치 force-block-{name}"
    assert gh_output(ws) == "go=false\n"


@pytest.mark.parametrize("name", GATES)
def test_other_gate_labels_do_not_block(ws, name):
    others = [f"force-block-{g}" for g in GATES if g != name]
    assert run_gate(ws, name, labels_view(*others)) == 0
    data = read_stage(ws / "out", f"gate-{name}")
    assert data["go"] is True and data["decision"] == "PASS" and data["forced"] is False


def test_contract_keeps_labels_and_state(ws):
    assert run_gate(ws, "merge", labels_view("bug", "force-block-release", state="OPEN")) == 0
    data = read_stage(ws / "out", "gate-merge")
    assert data["labels"] == ["bug", "force-block-release"]
    assert data["pr_state"] == "OPEN"


def test_gh_pr_view_args(ws):
    fake = labels_view()
    assert run_gate(ws, "release", fake) == 0
    assert fake.calls == [["gh", "pr", "view", PR, "-R", REPO, "--json", "labels,state"]]


@pytest.mark.parametrize("name", GATES)
@pytest.mark.parametrize("response", [
    proc(code=1, stderr="HTTP 404"),
    proc("not json"),
    proc(json.dumps({"state": "OPEN"})),
    proc(json.dumps({"labels": [{"nome": "x"}], "state": "OPEN"})),
], ids=["exit1", "broken-json", "no-labels", "bad-label"])
def test_label_read_failure_is_fail_closed(ws, capsys, name, response):
    assert run_gate(ws, name, Fake(response)) == 1
    assert not (ws / "out" / f"gate-{name}.json").exists()
    assert not (ws / "gh_out").exists()
    assert f"gate-{name}" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["--repo", "--pr"])
def test_repo_and_pr_required(ws, missing):
    argv = ["--workspace", str(ws), "--gate", "merge", "--repo", REPO, "--pr", PR]
    i = argv.index(missing)
    del argv[i:i + 2]
    with pytest.raises(SystemExit):
        gate.main(argv, runner=labels_view())
