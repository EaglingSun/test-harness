"""loop/gate.py 1차 임시 기준 (R12, ADR-007). 판정 함수는 순수 함수, main 은 fake runner만 쓴다 (ADR-004)."""

import json
import subprocess

import pytest

from loop import gate
from loop.contract import read_stage, write_stage

SHA = "c" * 40
A, B, C, D = (f"suite::case_{i}" for i in range(4))


def report(stage: str = "reverify", status: str = "ok", unexpected=(), fixed=(), missing=(),
           expected_head=()) -> dict:
    return {"stage": stage, "status": status, "make_outcome": "failure", "total": 5, "failed": list(unexpected),
            "unexpected": list(unexpected), "fixed": list(fixed), "missing": list(missing), "head_sha": SHA,
            "expected_base": [], "expected_head": list(expected_head)}


def review(status: str = "ok", critical: int = 0, errors=(), critical_posted: bool = False) -> dict:
    return {"stage": "review", "status": status, "mode": "stub",
            "counts": {"critical": critical, "major": 0, "minor": 0}, "critical_by_category": {},
            "event": "COMMENT", "posted": False, "errors": list(errors), "critical_posted": critical_posted}


def merged(flag: bool = True) -> dict:
    return {"stage": "merge", "merged": flag, "merge_sha": "9" * 40 if flag else "", "noop": False}


def gate_merge(degraded: bool = False) -> dict:
    return {"stage": "gate-merge", "gate": "merge", "go": True, "decision": "PASS", "reason": "r",
            "forced": False, "degraded": degraded}


# ---- autofix ----

def test_autofix_test_error_needs_investigation():
    go, decision, _ = gate.decide_autofix(report("test", status="error"))
    assert (go, decision) == (False, "NEEDS_INVESTIGATION")


@pytest.mark.parametrize("n, expected", [
    (0, (False, "NO_ACTION")),
    (1, (True, "AUTO_FIX")),
    (3, (True, "AUTO_FIX")),
    (4, (False, "NEEDS_HUMAN")),
])
def test_autofix_unexpected_boundaries(n, expected):
    go, decision, reason = gate.decide_autofix(report("test", unexpected=[f"s::c{i}" for i in range(n)]))
    assert (go, decision) == expected
    assert str(n) in reason


def test_autofix_max_is_3():
    assert gate.AUTOFIX_MAX == 3


# ---- merge ----

def test_merge_reverify_error_blocks():
    go, decision, reason, degraded = gate.decide_merge(report(status="error"), review())
    assert (go, decision, degraded) == (False, "BLOCK", False)
    assert "판정 불가" in reason and "reverify error" in reason


@pytest.mark.parametrize("kw", [{"unexpected": [A]}, {"missing": [A]}, {"unexpected": [A], "missing": [B]}])
def test_merge_unexpected_or_missing_blocks(kw):
    go, decision, reason, _ = gate.decide_merge(report(**kw), review())
    assert (go, decision) == (False, "BLOCK")
    for ident in kw.values():
        assert ident[0] in reason


def test_merge_fixed_still_listed_blocks():
    go, decision, reason, _ = gate.decide_merge(report(fixed=[A, B], expected_head=[B, C]), review())
    assert (go, decision) == (False, "BLOCK")
    assert "목록 갱신 필요(사람 몫)" in reason and B in reason and A not in reason


def test_merge_fixed_removed_from_head_passes():
    go, decision, _, degraded = gate.decide_merge(report(fixed=[A], expected_head=[C]), review())
    assert (go, decision, degraded) == (True, "PASS", False)


def test_merge_clean_passes():
    assert gate.decide_merge(report(), review())[:2] == (True, "PASS")


def test_merge_review_error_is_degraded_but_keeps_decision():
    go, decision, reason, degraded = gate.decide_merge(report(), review(status="error"))
    assert (go, decision, degraded) == (True, "PASS", True)
    assert reason.endswith("리뷰 실패 — 리뷰 없이 판정")
    go, decision, reason, degraded = gate.decide_merge(report(unexpected=[A]), review(status="error"))
    assert (go, decision, degraded) == (False, "BLOCK", True)


def test_merge_review_partial_failure_is_degraded_but_keeps_decision():
    partial = review(errors=["agent security: permission denied: Bash"])
    go, decision, reason, degraded = gate.decide_merge(report(), partial)
    assert (go, decision, degraded) == (True, "PASS", True)
    assert reason.endswith("리뷰 부분 실패 1건")
    go, decision, reason, degraded = gate.decide_merge(report(unexpected=[A]), partial)
    assert (go, decision, degraded) == (False, "BLOCK", True)
    assert "리뷰 부분 실패 1건" in reason


def test_merge_review_all_ok_not_degraded():
    go, decision, reason, degraded = gate.decide_merge(report(), review(errors=[]))
    assert (go, decision, degraded) == (True, "PASS", False)
    assert "부분 실패" not in reason


def test_merge_raw_critical_without_posted_does_not_block():
    # 판정 근거는 게시 기준 critical_posted 다. 원천 counts critical 은 막지도 표시하지도 않는다 (R15).
    go, decision, reason, _ = gate.decide_merge(report(), review(critical=2, critical_posted=False))
    assert (go, decision) == (True, "PASS")
    assert "critical" not in reason


def test_merge_critical_posted_needs_human():
    go, decision, reason, degraded = gate.decide_merge(report(), review(critical_posted=True))
    assert (go, decision, degraded) == (False, "NEEDS_HUMAN", False)
    assert reason == "리뷰 critical — 사람 확인 필요(라벨 review-accepted)"


def test_merge_critical_posted_accepted_passes():
    go, decision, reason, _ = gate.decide_merge(report(), review(critical_posted=True), accepted=True)
    assert (go, decision) == (True, "PASS")
    assert reason.endswith(" · 리뷰 critical — review-accepted 로 사람 확인됨")


def test_merge_accepted_without_critical_adds_nothing():
    _, _, reason, _ = gate.decide_merge(report(), review(), accepted=True)
    assert reason == "reverify 통과"


def test_merge_reverify_block_beats_critical_posted():
    go, decision, reason, _ = gate.decide_merge(report(unexpected=[A]), review(critical_posted=True))
    assert (go, decision) == (False, "BLOCK")
    assert A in reason and "review-accepted" not in reason


def test_merge_critical_posted_keeps_partial_failure_mark():
    partial = review(errors=["agent security: timeout"], critical_posted=True)
    go, decision, reason, degraded = gate.decide_merge(report(), partial)
    assert (go, decision, degraded) == (False, "NEEDS_HUMAN", True)
    assert reason.endswith("리뷰 부분 실패 1건")


# ---- release ----

def test_release_not_merged_blocks():
    go, decision, _, _ = gate.decide_release(merged(False), report(), gate_merge())
    assert (go, decision) == (False, "BLOCK")


@pytest.mark.parametrize("rv", [report(status="error"), report(unexpected=[A]), report(missing=[A]),
                                report(fixed=[A], expected_head=[A])], ids=["error", "unexpected", "missing", "fixed"])
def test_release_reverify_not_passing_blocks(rv):
    go, decision, _, _ = gate.decide_release(merged(), rv, gate_merge())
    assert (go, decision) == (False, "BLOCK")


@pytest.mark.parametrize("deg", [False, True])
def test_release_passes_and_carries_degraded(deg):
    go, decision, _, degraded = gate.decide_release(merged(), report(), gate_merge(degraded=deg))
    assert (go, decision, degraded) == (True, "PASS", deg)


# ---- main: 강제 스위치가 기준보다 먼저 · degraded 전파 · exit code ----

def labels(*names: str):
    def runner(args, input=None):
        assert args[:3] == ["gh", "pr", "view"], args
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(
            {"labels": [{"name": n} for n in names], "state": "OPEN"}), stderr="")
    return runner


def run_gate(ws, name: str, *names: str) -> int:
    return gate.main(["--workspace", str(ws), "--gate", name, "--repo", "o/r", "--pr", "7"], runner=labels(*names))


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    return tmp_path / "out"


def test_main_autofix_auto_fix_and_switch_first(out):
    write_stage(out, "test", report("test", unexpected=[A]))
    write_stage(out, "review", review())
    assert run_gate(out.parent, "autofix") == 0
    assert read_stage(out, "gate-autofix")["decision"] == "AUTO_FIX"
    assert run_gate(out.parent, "autofix", "force-block-autofix") == 0
    data = read_stage(out, "gate-autofix")
    assert data["go"] is False and data["decision"] == "BLOCK" and data["forced"] is True


@pytest.mark.parametrize("decision_case, code", [("NO_ACTION", 0), ("NEEDS_HUMAN", 0)])
def test_main_autofix_always_exit_0(out, decision_case, code):
    n = 0 if decision_case == "NO_ACTION" else 4
    write_stage(out, "test", report("test", unexpected=[f"s::c{i}" for i in range(n)]))
    write_stage(out, "review", review())
    assert run_gate(out.parent, "autofix") == code
    data = read_stage(out, "gate-autofix")
    assert data["go"] is False and data["decision"] == decision_case


def test_main_merge_block_exit_1(out):
    write_stage(out, "reverify", report(missing=[A]))
    write_stage(out, "review", review())
    assert run_gate(out.parent, "merge") == 1
    assert read_stage(out, "gate-merge")["decision"] == "BLOCK"


def test_main_merge_critical_posted_needs_human_exit_1(out):
    write_stage(out, "reverify", report())
    write_stage(out, "review", review(critical_posted=True))
    assert run_gate(out.parent, "merge") == 1
    data = read_stage(out, "gate-merge")
    assert data["go"] is False and data["decision"] == "NEEDS_HUMAN" and data["forced"] is False


def test_main_merge_review_accepted_label_passes_exit_0(out):
    write_stage(out, "reverify", report())
    write_stage(out, "review", review(critical_posted=True))
    assert run_gate(out.parent, "merge", "review-accepted") == 0
    data = read_stage(out, "gate-merge")
    assert data["go"] is True and data["decision"] == "PASS"
    assert "review-accepted" in data["reason"]


def test_main_merge_switch_beats_review_accepted(out):
    write_stage(out, "reverify", report())
    write_stage(out, "review", review(critical_posted=True))
    assert run_gate(out.parent, "merge", "review-accepted", "force-block-merge") == 1
    data = read_stage(out, "gate-merge")
    assert data["decision"] == "BLOCK" and data["forced"] is True


def test_main_merge_switch_beats_passing_criteria(out):
    write_stage(out, "reverify", report())
    write_stage(out, "review", review(status="error"))
    assert run_gate(out.parent, "merge", "force-block-merge") == 1
    data = read_stage(out, "gate-merge")
    assert data["decision"] == "BLOCK" and data["forced"] is True
    assert data["reason"] == "강제 스위치 force-block-merge"
    assert data["degraded"] is True


def test_main_degraded_propagates_merge_to_release(out):
    write_stage(out, "reverify", report())
    write_stage(out, "review", review(status="error"))
    assert run_gate(out.parent, "merge") == 0
    assert read_stage(out, "gate-merge")["degraded"] is True
    write_stage(out, "merge", merged())
    assert run_gate(out.parent, "release") == 0
    data = read_stage(out, "gate-release")
    assert data["decision"] == "PASS" and data["degraded"] is True


def test_main_release_requires_gate_merge(out, capsys):
    write_stage(out, "reverify", report())
    write_stage(out, "merge", merged())
    assert run_gate(out.parent, "release") == 1
    assert not (out / "gate-release.json").exists()
    assert "gate-merge.json" in capsys.readouterr().err
