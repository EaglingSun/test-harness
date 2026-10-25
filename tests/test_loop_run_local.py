"""loop/run_local.py — fake runner로 전 단계 한 바퀴 (R7). 실제 git/gh는 실행하지 않는다."""

import shutil
from pathlib import Path

from loop.contract import read_stage
from loop.run_local import main

FIXTURE = Path(__file__).parent / "fixtures" / "loop" / "basic"


def test_run_local_basic(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path)]) == 0
    release = read_stage(tmp_path / "out", "release")
    assert release["prerelease"] is True and release["tag"].startswith("loop-pr1-")
    assert read_stage(tmp_path / "out", "reverify")["unexpected"] == []
    assert read_stage(tmp_path / "out", "gate-autofix")["decision"] == "NO_ACTION"
    assert not (tmp_path / "out" / "fix.json").exists()
    assert read_stage(tmp_path / "out", "gate-merge")["decision"] == "PASS"
    assert "release" in capsys.readouterr().out


def test_run_local_force_block_autofix(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path), "--labels", "force-block-autofix"]) == 0
    out = tmp_path / "out"
    assert read_stage(out, "gate-autofix")["go"] is False
    assert not (out / "fix.json").exists()
    assert read_stage(out, "release")["prerelease"] is True
    assert "skipped" in [line.split()[1] for line in capsys.readouterr().out.splitlines()
                         if line.startswith("fix ")]


def test_run_local_force_block_merge(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path), "--labels", "force-block-merge"]) == 0
    out = tmp_path / "out"
    assert read_stage(out, "gate-merge")["decision"] == "BLOCK"
    for name in ("merge", "gate-release", "release"):
        assert not (out / f"{name}.json").exists()
    lines = {line.split()[0]: line.split()[1] for line in capsys.readouterr().out.splitlines()
             if line.strip() and not line.startswith("==")}
    assert lines["merge"] == lines["gate-release"] == lines["release"] == "skipped"
    assert lines["reverify"] != "skipped"


def test_run_local_force_block_release(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path), "--labels", "force-block-release"]) == 0
    out = tmp_path / "out"
    assert read_stage(out, "merge")["merged"] is True
    assert read_stage(out, "gate-release")["decision"] == "BLOCK"
    assert not (out / "release.json").exists()
    lines = {line.split()[0]: line.split()[1] for line in capsys.readouterr().out.splitlines()
             if line.strip() and not line.startswith("==")}
    assert lines["release"] == "skipped"


# ---- 1차 임시 기준(R12) fixture 흐름 ----

STAGES = ("test", "review", "gate-autofix", "fix", "reverify", "gate-merge", "merge", "gate-release", "release")


def run_fixture(name_or_path, tmp_path, capsys) -> tuple[Path, dict[str, str]]:
    fixture = name_or_path if isinstance(name_or_path, Path) else FIXTURE.parent / name_or_path
    ws = tmp_path / "ws"
    assert main(["--fixture", str(fixture), "--out", str(ws)]) == 0
    summary = capsys.readouterr().out.split("== loop run_local ==")[-1]
    lines = {line.split()[0]: line.split()[1] for line in summary.splitlines() if line.strip()}
    assert list(lines) == list(STAGES)
    return ws / "out", lines


def skipped(lines: dict[str, str]) -> set[str]:
    return {name for name, first in lines.items() if first == "skipped"}


def test_flow_new_defect(tmp_path, capsys):
    out, lines = run_fixture("new-defect", tmp_path, capsys)
    assert read_stage(out, "test")["unexpected"] == ["test_diag_log::SR-011_numeric_parses"]
    autofix = read_stage(out, "gate-autofix")
    assert autofix["go"] is True and autofix["decision"] == "AUTO_FIX"
    assert read_stage(out, "fix")["status"] == "ok"
    merge = read_stage(out, "gate-merge")
    assert merge["go"] is False and merge["decision"] == "BLOCK"
    assert "test_diag_log::SR-011_numeric_parses" in merge["reason"]
    assert skipped(lines) == {"merge", "gate-release", "release"}
    assert not (out / "release.json").exists()


def test_flow_fixed_unlisted(tmp_path, capsys):
    out, lines = run_fixture("fixed-unlisted", tmp_path, capsys)
    assert read_stage(out, "gate-autofix")["decision"] == "NO_ACTION"
    merge = read_stage(out, "gate-merge")
    assert merge["decision"] == "BLOCK" and "목록 갱신 필요(사람 몫)" in merge["reason"]
    assert "test_diag_log::SR-011_empty_returns_minus1" in merge["reason"]
    assert skipped(lines) == {"fix", "merge", "gate-release", "release"}
    assert not (out / "release.json").exists()


def test_flow_fixed_listed(tmp_path, capsys):
    out, lines = run_fixture("fixed-listed", tmp_path, capsys)
    assert read_stage(out, "reverify")["fixed"] == ["test_diag_log::SR-011_empty_returns_minus1"]
    assert read_stage(out, "gate-merge")["decision"] == "PASS"
    assert read_stage(out, "gate-release")["decision"] == "PASS"
    assert skipped(lines) == {"fix"}
    assert read_stage(out, "release")["prerelease"] is True


def test_flow_build_broken(tmp_path, capsys):
    out, lines = run_fixture("build-broken", tmp_path, capsys)
    assert read_stage(out, "test")["status"] == "error"
    assert read_stage(out, "gate-autofix")["decision"] == "NEEDS_INVESTIGATION"
    assert read_stage(out, "reverify")["status"] == "error"
    merge = read_stage(out, "gate-merge")
    assert merge["decision"] == "BLOCK" and "판정 불가" in merge["reason"]
    assert skipped(lines) == {"fix", "merge", "gate-release", "release"}
    assert not (out / "release.json").exists()


def test_flow_reverify_results_used_when_present(tmp_path, capsys):
    """fixture 에 reverify-results/ 가 있으면 reverify 는 그 XML 을 쓴다: new-defect → fix 후 basic 결과 → release."""
    fixture = tmp_path / "fx"
    shutil.copytree(FIXTURE.parent / "new-defect", fixture)
    shutil.copytree(FIXTURE / "test-results", fixture / "reverify-results")
    out, lines = run_fixture(fixture, tmp_path, capsys)
    assert read_stage(out, "gate-autofix")["decision"] == "AUTO_FIX"
    assert read_stage(out, "test")["unexpected"] == ["test_diag_log::SR-011_numeric_parses"]
    assert read_stage(out, "reverify")["unexpected"] == []
    assert read_stage(out, "gate-merge")["decision"] == "PASS"
    assert skipped(lines) == set()
    assert read_stage(out, "release")["prerelease"] is True
