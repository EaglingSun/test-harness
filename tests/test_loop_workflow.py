"""PR 루프 workflow 틀(loop/templates/pr-loop.yml) 구조 검사 — ADR-006 (R8).

YAML 구조만 본다. GitHub 에서 실제로 도는지는 phase 완료 후 E2E 로만 확인된다.
PyYAML 은 테스트에서만 쓴다(ADR-006).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "loop" / "templates" / "pr-loop.yml"

CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
DOWNLOAD = "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"
UPLOAD = "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
ALLOWED_USES = {CHECKOUT, DOWNLOAD, UPLOAD}
PINNED = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}")

NEEDS = {
    "test": [],
    "review": ["test"],
    "autofix-gate": ["test", "review"],
    "fix": ["autofix-gate"],
    "reverify": ["autofix-gate", "fix"],
    "merge-gate": ["reverify"],
    "merge": ["merge-gate"],
    "release-gate": ["merge"],
    "release": ["release-gate"],
}

# job → 그 job 이 upload 해야 하는 artifact 이름
UPLOADS = {
    "test": "loop-test",
    "review": "loop-review",
    "autofix-gate": "loop-gate-autofix",
    "fix": "loop-fix",
    "reverify": "loop-reverify",
    "merge-gate": "loop-gate-merge",
    "merge": "loop-merge",
    "release-gate": "loop-gate-release",
    "release": "loop-release",
}

LOOP_CALL = re.compile(r"py -m (loop\.[a-z_]+)")


@pytest.fixture(scope="module")
def text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(text) -> dict:
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def jobs(wf) -> dict:
    return wf["jobs"]


def all_steps(jobs: dict) -> list[dict]:
    return [s for j in jobs.values() for s in j["steps"]]


def needs_of(job: dict) -> list[str]:
    n = job.get("needs", [])
    return [n] if isinstance(n, str) else list(n)


def make_step(job: dict) -> dict:
    found = [s for s in job["steps"] if s.get("run", "").strip() == r".\make.cmd test"]
    assert len(found) == 1, f"make step 이 1개가 아니라 {len(found)}개"
    return found[0]


def test_triggers_pull_request_master(wf):
    on = wf.get("on", wf.get(True))  # PyYAML 은 키 on 을 불리언 True 로 읽는다
    assert list(on) == ["pull_request"]
    assert on["pull_request"]["branches"] == ["master"]
    assert on["pull_request"]["types"] == ["opened", "synchronize", "reopened", "labeled"]


def test_labeled_runs_only_for_force_block(jobs):
    cond = jobs["test"]["if"]
    assert "github.event.action != 'labeled'" in cond
    assert "startsWith(github.event.label.name, 'force-block-')" in cond


def test_no_secrets_or_dispatch(text):
    assert "secrets." not in text  # GITHUB_TOKEN 만 (ADR-006)
    assert "workflow_dispatch" not in text
    assert "pull_request_target" not in text


def test_permissions_and_token(wf, jobs):
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert all("permissions" not in j for j in jobs.values())  # job 수준에서 넓히지 않는다
    assert wf["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_concurrency_per_pr_no_cancel(wf):
    assert "github.event.pull_request.number" in wf["concurrency"]["group"]
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_concurrency_separates_non_force_block_labels(wf):
    group = wf["concurrency"]["group"]
    assert "github.run_id" in group  # 아무 라벨 run 이 진짜 pending run 을 밀어내지 않게
    assert "force-block-" in group


def test_job_chain_matches(jobs):
    assert list(jobs) == list(NEEDS)
    assert {name: needs_of(j) for name, j in jobs.items()} == NEEDS


@pytest.mark.parametrize("name", list(NEEDS))
def test_job_common_rules(jobs, name):
    job = jobs[name]
    assert job["runs-on"] == ["self-hosted", "vsm-loop"]
    assert job["timeout-minutes"] <= 30
    first = job["steps"][0]
    assert first.get("uses") == CHECKOUT
    assert first["with"]["fetch-depth"] == 0
    assert "github.head_ref" in first["with"]["ref"]


def test_uses_pinned_and_allowed(jobs):
    uses = [s["uses"] for s in all_steps(jobs) if "uses" in s]
    assert uses
    for u in uses:
        assert PINNED.fullmatch(u), f"40자 커밋 SHA 고정이 아님: {u}"
        assert u in ALLOWED_USES, f"허용 목록 밖 action: {u}"


def test_download_merges_loop_artifacts_into_out(jobs):
    downloads = [s for s in all_steps(jobs) if s.get("uses") == DOWNLOAD]
    assert downloads
    for s in downloads:
        assert s["with"] == {"pattern": "loop-*", "merge-multiple": True, "path": "out"}


@pytest.mark.parametrize("name", ["test", "reverify"])
def test_make_step_does_not_judge(jobs, name):
    step = make_step(jobs[name])
    assert step["continue-on-error"] is True
    assert step["shell"] == "cmd"
    assert step["id"] == "make"


def test_fix_runs_only_when_gate_go(jobs):
    assert "needs.autofix-gate.outputs.go == 'true'" in jobs["fix"]["if"]
    assert jobs["autofix-gate"]["outputs"]["go"] == "${{ steps.gate.outputs.go }}"
    assert any(s.get("id") == "gate" for s in jobs["autofix-gate"]["steps"])


def test_fix_mode_from_repo_variable(jobs, text):
    runs = [s["run"] for s in jobs["fix"]["steps"] if "py -m loop.fix" in s.get("run", "")]
    assert len(runs) == 1
    assert "--mode ${{ vars.LOOP_FIX_MODE || 'stub' }}" in runs[0]
    assert "--mode stub" not in runs[0]
    assert "LOOP_FIX_MODE" in text.split("name: pr-loop")[0]  # 머리 주석 변수 목록


def test_reverify_runs_when_fix_skipped(jobs):
    cond = jobs["reverify"]["if"]
    assert "!cancelled()" in cond
    assert "needs.autofix-gate.result == 'success'" in cond
    assert "needs.fix.result == 'success'" in cond
    assert "needs.fix.result == 'skipped'" in cond


def descendants(jobs: dict, root: str) -> list[str]:
    """needs 그래프에서 root 의 모든 후손 job (workflow 순서)."""
    found = {root}
    for name, job in jobs.items():  # job 은 needs 보다 뒤에 정의된다(test_job_chain_matches)
        if found & set(needs_of(job)):
            found.add(name)
    found.discard(root)
    return [name for name in jobs if name in found]


# GitHub Actions 의 job 기본 조건 success() 는 직접 needs 만이 아니라 조상 job 중 하나라도
# skip/실패면 거짓이다. 그래서 fix 가 skip(go=false)되면 그 후손은 명시적 if 가 없으면 전부 skip 된다.
# E2E 근거: 리허설 저장소 PR #3 (run 40201593699) — NO_ACTION PR 에서 merge-gate 이후가 모두 skip.
# 후손 목록은 needs 에서 계산한다(job 이 늘어도 잡히게). if: always() 는 취소된 run 에서도 돌므로 쓰지 않는다.
def test_fix_descendants_run_when_fix_skipped(jobs):
    desc = descendants(jobs, "fix")
    assert desc == ["reverify", "merge-gate", "merge", "release-gate", "release"]
    for name in desc:
        cond = jobs[name].get("if", "")
        assert "!cancelled()" in cond, f"{name}: !cancelled() 없음"
        assert "always()" not in cond, f"{name}: always() 금지"
        if name == "reverify":
            continue  # fix skip 을 직접 허용하는 조건은 test_reverify_runs_when_fix_skipped 가 본다
        for need in needs_of(jobs[name]):
            assert f"needs.{need}.result == 'success'" in cond, f"{name}: needs.{need}.result 검사 없음"


def test_loop_steps_run_in_loop_home_with_workspace(jobs):
    loop_steps = [s for s in all_steps(jobs) if LOOP_CALL.search(s.get("run", ""))]
    assert len(loop_steps) == len(NEEDS)  # 단계마다 하나
    for s in loop_steps:
        assert s["working-directory"] == "${{ vars.LOOP_HOME }}"
        assert '--workspace "${{ github.workspace }}"' in s["run"]


@pytest.mark.parametrize("name", list(UPLOADS))
def test_stage_uploads_named_artifact(jobs, name):
    uploads = [s["with"] for s in jobs[name]["steps"] if s.get("uses") == UPLOAD]
    stage = [w for w in uploads if w["name"] == UPLOADS[name]]
    assert len(stage) == 1, f"{name}: {UPLOADS[name]} upload 가 1개가 아님"
    w = stage[0]
    assert w["path"] == f"out/{UPLOADS[name].removeprefix('loop-')}.json"
    assert w["overwrite"] is True
    assert w["if-no-files-found"] == "error"


def test_test_job_uploads_junit(jobs):
    names = [s["with"]["name"] for s in jobs["test"]["steps"] if s.get("uses") == UPLOAD]
    assert "loop-junit" in names


@pytest.mark.parametrize("name", ["autofix-gate", "merge-gate", "release-gate"])
def test_gate_step_passes_repo_and_pr(jobs, name):
    gate = [s for s in jobs[name]["steps"] if "py -m loop.gate" in s.get("run", "")]
    assert len(gate) == 1
    run = gate[0]["run"]
    assert "--repo ${{ github.repository }}" in run
    assert "--pr ${{ github.event.pull_request.number }}" in run


def test_header_lists_force_block_labels(text):
    header = text.split("\nname:", 1)[0]
    assert "gh label create" in header
    for label in ("force-block-autofix", "force-block-merge", "force-block-release"):
        assert label in header


def test_loop_modules_exist(text):
    modules = set(LOOP_CALL.findall(text))
    assert modules == {"loop.test_report", "loop.review", "loop.gate", "loop.fix", "loop.finish"}
    for m in modules:
        assert (ROOT / (m.replace(".", "/") + ".py")).is_file(), f"{m} 모듈 파일이 없다"
