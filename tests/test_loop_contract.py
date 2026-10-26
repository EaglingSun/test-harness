"""loop/contract.py — 단계 간 계약 JSON 검증 (ADR-006)."""

import json

import pytest

from loop.contract import ContractError, read_stage, stage_path, write_github_output, write_stage


def gate_data(**overrides) -> dict:
    data = {"stage": "gate-merge", "gate": "merge", "go": True, "decision": "PASS", "reason": "r",
            "forced": False, "degraded": False}
    data.update(overrides)
    return data


def test_roundtrip_keeps_unicode(tmp_path):
    data = gate_data(reason="무게이트")
    path = write_stage(tmp_path / "out", "gate-merge", data)
    assert path == stage_path(tmp_path / "out", "gate-merge")
    assert "무게이트" in path.read_text(encoding="utf-8")  # ensure_ascii=False
    assert read_stage(tmp_path / "out", "gate-merge") == data


def test_write_rejects_missing_key(tmp_path):
    data = gate_data()
    del data["go"]
    with pytest.raises(ContractError, match="go"):
        write_stage(tmp_path, "gate-merge", data)


def test_read_rejects_missing_key(tmp_path):
    stage_path(tmp_path, "merge").write_text('{"stage": "merge", "merged": true, "noop": false}', encoding="utf-8")
    with pytest.raises(ContractError, match="merge_sha"):
        read_stage(tmp_path, "merge")


def review_data(**overrides) -> dict:
    data = {"stage": "review", "status": "ok", "mode": "stub", "counts": {}, "critical_by_category": {},
            "event": "COMMENT", "posted": False, "errors": [], "critical_posted": False}
    data.update(overrides)
    return data


def test_read_rejects_review_without_critical_posted(tmp_path):
    data = review_data()
    del data["critical_posted"]
    stage_path(tmp_path, "review").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ContractError, match="critical_posted"):
        read_stage(tmp_path, "review")


def test_review_critical_posted_must_be_bool(tmp_path):
    write_stage(tmp_path, "review", review_data())
    with pytest.raises(ContractError, match="critical_posted"):
        write_stage(tmp_path, "review", review_data(critical_posted="true"))


def test_read_missing_file(tmp_path):
    with pytest.raises(ContractError, match="없다"):
        read_stage(tmp_path, "test")


def test_read_broken_json(tmp_path):
    stage_path(tmp_path, "review").write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError):
        read_stage(tmp_path, "review")


def test_bool_type_error(tmp_path):
    with pytest.raises(ContractError, match="go"):
        write_stage(tmp_path, "gate-merge", gate_data(go="true"))


def test_stage_value_must_match_name(tmp_path):
    with pytest.raises(ContractError):
        write_stage(tmp_path, "gate-release", gate_data())


def test_list_and_status_types(tmp_path):
    base = {"stage": "test", "status": "ok", "make_outcome": "success", "total": 1, "failed": [],
            "unexpected": [], "fixed": [], "missing": [], "head_sha": "abc", "expected_base": [],
            "expected_head": []}
    write_stage(tmp_path, "test", base)
    with pytest.raises(ContractError, match="failed"):
        write_stage(tmp_path, "test", {**base, "failed": "a::b"})
    with pytest.raises(ContractError, match="status"):
        write_stage(tmp_path, "test", {**base, "status": "PASS"})


def test_github_output_only_when_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    write_github_output("go", "true")  # env 없음: 아무것도 하지 않는다
    assert list(tmp_path.iterdir()) == []

    target = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(target))
    write_github_output("go", "true")
    write_github_output("decision", "PASS")
    assert target.read_text(encoding="utf-8") == "go=true\ndecision=PASS\n"
