"""loop/run_local.py — fake runner로 전 단계 한 바퀴 (R7). 실제 git/gh는 실행하지 않는다."""

from pathlib import Path

from loop.contract import read_stage
from loop.run_local import main

FIXTURE = Path(__file__).parent / "fixtures" / "loop" / "basic"


def test_run_local_basic(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path)]) == 0
    release = read_stage(tmp_path / "out", "release")
    assert release["prerelease"] is True and release["tag"].startswith("loop-pr1-")
    assert read_stage(tmp_path / "out", "reverify")["unexpected"] == []
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
    assert lines["fix"] != "skipped"


def test_run_local_force_block_release(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path), "--labels", "force-block-release"]) == 0
    out = tmp_path / "out"
    assert read_stage(out, "merge")["merged"] is True
    assert read_stage(out, "gate-release")["decision"] == "BLOCK"
    assert not (out / "release.json").exists()
    lines = {line.split()[0]: line.split()[1] for line in capsys.readouterr().out.splitlines()
             if line.strip() and not line.startswith("==")}
    assert lines["release"] == "skipped"
