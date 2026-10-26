"""loop/run_local.py — fake runner로 전 단계 한 바퀴 (R7). 실제 git/gh는 실행하지 않는다."""

from pathlib import Path

import pytest

from loop.contract import read_stage
from loop.run_local import main

FIXTURE = Path(__file__).parent / "fixtures" / "loop" / "basic"


def test_run_local_basic(tmp_path, capsys):
    assert main(["--fixture", str(FIXTURE), "--out", str(tmp_path)]) == 0
    release = read_stage(tmp_path / "out", "release")
    assert release["prerelease"] is True and release["tag"].startswith("loop-pr1-")
    assert read_stage(tmp_path / "out", "reverify")["unexpected"] == []
    assert "release" in capsys.readouterr().out


# 무게이트: 결함 · 빌드 깨짐 fixture 도 merge · release 까지 간다 (kit-5 와 같은 fixture)
@pytest.mark.parametrize("name, status, unexpected, fixed", [
    ("new-defect", "ok", 1, 0),
    ("fixed-listed", "ok", 0, 1),
    ("fixed-unlisted", "ok", 0, 1),
    ("build-broken", "error", None, None),
])
def test_run_local_nogate_passes_defects(tmp_path, name, status, unexpected, fixed):
    fixture = FIXTURE.parent / name
    assert main(["--fixture", str(fixture), "--out", str(tmp_path)]) == 0
    out = tmp_path / "out"
    for gate in ("gate-autofix", "gate-merge", "gate-release"):
        d = read_stage(out, gate)
        assert d["go"] is True and d["decision"] == "PASS", gate
    release = read_stage(out, "release")
    assert release["prerelease"] is True and release["tag"].startswith("loop-pr1-")
    test = read_stage(out, "test")
    assert test["status"] == status
    if unexpected is not None:
        assert len(test["unexpected"]) == unexpected
        assert len(test["fixed"]) == fixed
