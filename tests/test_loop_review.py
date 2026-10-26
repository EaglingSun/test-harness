"""loop.review real 모드 (R10). fake runner만 쓴다 — 실제 py -m pr_reviewer·gh·claude 실행 금지 (ADR-004)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from loop import review
from loop.contract import read_stage, write_stage
from pr_reviewer.aggregate import OWN_PR_CRITICAL

FIXTURE_PLAN = Path(__file__).parent / "fixtures" / "loop" / "review-plan.json"


def report_data() -> dict:
    return {"stage": "test", "status": "ok", "make_outcome": "failure", "total": 3, "failed": [],
            "unexpected": [], "fixed": [], "missing": [], "head_sha": "c" * 40, "expected_base": [],
            "expected_head": []}


class FakeReviewer:
    """pr_reviewer 프로세스 흉내: --plan-out 경로에 plan_text를 쓰고(None이면 안 씀) 고정 결과를 돌려준다."""

    def __init__(self, plan_text: str | None, code: int = 0, stderr: str = ""):
        self.plan_text = plan_text
        self.code = code
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(list(args))
        if self.plan_text is not None:
            Path(args[args.index("--plan-out") + 1]).write_text(self.plan_text, encoding="utf-8")
        return subprocess.CompletedProcess(args, self.code, stdout="", stderr=self.stderr)


def run_real(tmp_path: Path, fake: FakeReviewer, *extra: str) -> int:
    write_stage(tmp_path / "out", "test", report_data())
    argv = ["--workspace", str(tmp_path), "--mode", "real", "--repo", "o/r", "--pr", "7", *extra]
    return review.main(argv, runner=fake)


def test_real_argv_exact(tmp_path):
    fake = FakeReviewer(FIXTURE_PLAN.read_text(encoding="utf-8"))
    assert run_real(tmp_path, fake) == 0
    out = tmp_path / "out"
    assert fake.calls == [[
        sys.executable, "-m", "pr_reviewer", "o/r", "7",
        "--junit-dir", str(out), "--plan-out", str(out / "review-plan.json"),
        "--current-user", "github-actions[bot]",
    ]]


def test_real_current_user_option(tmp_path):
    fake = FakeReviewer(FIXTURE_PLAN.read_text(encoding="utf-8"))
    assert run_real(tmp_path, fake, "--current-user", "alice") == 0
    argv = fake.calls[0]
    assert argv[argv.index("--current-user") + 1] == "alice"


def test_real_converts_plan(tmp_path):
    fake = FakeReviewer(FIXTURE_PLAN.read_text(encoding="utf-8"))
    assert run_real(tmp_path, fake) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["status"] == "ok" and data["mode"] == "real"
    assert data["counts"] == {"critical": 1, "major": 2, "minor": 1}
    assert data["counts_basis"] == "agent_raw"
    assert data["critical_by_category"] == {"security": 1}
    assert data["event"] == "REQUEST_CHANGES"
    assert data["errors"] == ["claude 실행 실패: timeout"]
    assert data["posted"] is True
    assert data["critical_posted"] is True  # fixture event REQUEST_CHANGES


def plan_text(event: str, summary: str) -> str:
    plan = json.loads(FIXTURE_PLAN.read_text(encoding="utf-8"))
    plan["event"], plan["summary_markdown"] = event, summary
    return json.dumps(plan, ensure_ascii=False)


# critical_posted 는 게시 기준(ADR-005 강등 뒤): REQUEST_CHANGES 거나, 자기 PR 이라 COMMENT 로 바꾼 요약 문구 (R15)
@pytest.mark.parametrize("event, summary, expected", [
    ("REQUEST_CHANGES", "## 요약", True),
    ("COMMENT", f"## 요약\n\n> **{OWN_PR_CRITICAL}**\n", True),
    ("COMMENT", "## 요약", False),
], ids=["request_changes", "own_pr_critical", "comment_only"])
def test_real_critical_posted_from_plan(tmp_path, event, summary, expected):
    assert run_real(tmp_path, FakeReviewer(plan_text(event, summary))) == 0
    assert read_stage(tmp_path / "out", "review")["critical_posted"] is expected


def test_real_critical_posted_false_without_plan(tmp_path):
    assert run_real(tmp_path, FakeReviewer(None, code=1, stderr="boom\n")) == 0
    assert read_stage(tmp_path / "out", "review")["critical_posted"] is False


def test_real_process_failure_without_plan(tmp_path):
    fake = FakeReviewer(None, code=1, stderr="Traceback ...\nGhError: gh api 실패\n")
    assert run_real(tmp_path, fake) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["status"] == "error"
    assert data["posted"] is False
    assert any("GhError: gh api 실패" in e for e in data["errors"])


def test_real_process_failure_with_plan(tmp_path):
    # 계획 저장 후 게시가 실패한 경우: 집계는 남기되 posted false · status error
    fake = FakeReviewer(FIXTURE_PLAN.read_text(encoding="utf-8"), code=1, stderr="게시 실패\n")
    assert run_real(tmp_path, fake) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["status"] == "error" and data["posted"] is False
    assert "claude 실행 실패: timeout" in data["errors"]
    assert any("게시 실패" in e for e in data["errors"])


def test_real_exit0_but_no_plan(tmp_path):
    fake = FakeReviewer(None, code=0)
    assert run_real(tmp_path, fake) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["status"] == "error" and data["posted"] is False
    assert data["errors"]


def test_real_broken_plan_json(tmp_path):
    fake = FakeReviewer("{not json", code=0)
    assert run_real(tmp_path, fake) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data["status"] == "error" and data["posted"] is False
    assert data["errors"]


def test_real_requires_test_contract(tmp_path, capsys):
    fake = FakeReviewer(FIXTURE_PLAN.read_text(encoding="utf-8"))
    argv = ["--workspace", str(tmp_path), "--mode", "real", "--repo", "o/r", "--pr", "7"]
    assert review.main(argv, runner=fake) == 1
    assert fake.calls == []
    assert "test.json" in capsys.readouterr().err


def test_stub_unchanged(tmp_path):
    write_stage(tmp_path / "out", "test", report_data())

    def no_runner(args, input=None):
        raise AssertionError(f"stub 모드는 외부 호출이 없어야 한다: {args}")

    argv = ["--workspace", str(tmp_path), "--mode", "stub", "--repo", "o/r", "--pr", "1"]
    assert review.main(argv, runner=no_runner) == 0
    data = read_stage(tmp_path / "out", "review")
    assert data == {
        "stage": "review", "status": "ok", "mode": "stub",
        "counts": {"critical": 0, "major": 1, "minor": 1},
        "critical_by_category": {}, "event": "COMMENT", "posted": False, "errors": [],
        "critical_posted": False,
    }
