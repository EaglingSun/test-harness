"""proc.run_process 인자 전달 — subprocess.run 은 monkeypatch 로 대체한다. 실제 프로세스는 실행하지 않는다."""

import subprocess

from pr_reviewer import proc


def capture(monkeypatch) -> dict:
    seen: dict = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    return seen


def test_run_process_passes_cwd(monkeypatch):
    seen = capture(monkeypatch)
    proc.run_process(["claude", "-p"], "프롬프트", timeout=600, cwd="C:/ws")
    assert seen["cwd"] == "C:/ws" and seen["timeout"] == 600 and seen["input"] == "프롬프트"


def test_run_process_two_positional_args_unchanged(monkeypatch):
    seen = capture(monkeypatch)
    proc.run_process(["gh", "api", "user"], None)
    assert seen["args"] == ["gh", "api", "user"]
    assert seen["cwd"] is None and seen["timeout"] == 900 and seen["input"] is None
    assert seen["shell"] is False and seen["capture_output"] is True and seen["check"] is False
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace" and seen["text"] is True
