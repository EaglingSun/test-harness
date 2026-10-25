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
