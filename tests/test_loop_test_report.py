"""loop/test_report.py — test · reverify 단계 분류. fake runner만 쓴다 (ADR-004)."""

import json
import shutil
import subprocess
from pathlib import Path

from loop.test_report import classify, main, parse_expect, parse_results

FIXTURE = Path(__file__).parent / "fixtures" / "loop" / "basic"
BASE_TEXT = (FIXTURE / "expected-base.txt").read_text(encoding="utf-8")
SHA = "a" * 40


class GitFake:
    def __init__(self, base_text: str = BASE_TEXT, show_code: int = 0):
        self.base_text = base_text
        self.show_code = show_code
        self.calls: list[list[str]] = []

    def __call__(self, args, input=None):
        self.calls.append(args)
        assert args[:2] == ["git", "-C"]
        if args[3] == "show":
            if self.show_code:
                return subprocess.CompletedProcess(args, self.show_code, stdout="", stderr="fatal: bad revision")
            return subprocess.CompletedProcess(args, 0, stdout=self.base_text, stderr="")
        if args[3] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout=SHA + "\n", stderr="")
        raise AssertionError(f"예상하지 못한 명령 {args}")


def make_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE / "test-results", ws / "test-results")
    (ws / "tests").mkdir()
    shutil.copy2(FIXTURE / "tests" / "expected_failures.txt", ws / "tests" / "expected_failures.txt")
    return ws


def run(ws: Path, runner, stage="test") -> tuple[int, dict]:
    code = main(["--workspace", str(ws), "--stage", stage, "--make-outcome", "failure",
                 "--base-ref", "origin/master"], runner=runner)
    return code, json.loads((ws / "out" / f"{stage}.json").read_text(encoding="utf-8"))


def edit_xml(ws: Path, name: str, old: str, new: str) -> None:
    path = ws / "test-results" / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_basic_fixture_all_known(tmp_path):
    ws = make_ws(tmp_path)
    fake = GitFake()
    code, data = run(ws, fake)
    assert code == 0
    assert data["status"] == "ok"
    assert data["make_outcome"] == "failure"
    assert len(data["failed"]) == 8
    assert data["unexpected"] == data["fixed"] == data["missing"] == []
    assert data["head_sha"] == SHA
    assert data["expected_base"] == data["expected_head"] == sorted(data["failed"])
    assert ["git", "-C", str(ws), "show", "origin/master:tests/expected_failures.txt"] in fake.calls


def test_passing_case_now_fails_is_unexpected(tmp_path):
    ws = make_ws(tmp_path)
    edit_xml(ws, "test_diag_log.xml", 'name="SR-011_numeric_parses"/>',
             'name="SR-011_numeric_parses"><failure message="boom"/></testcase>')
    _, data = run(ws, GitFake())
    assert data["unexpected"] == ["test_diag_log::SR-011_numeric_parses"]
    assert len(data["failed"]) == 9


def test_error_element_counts_as_failure(tmp_path):
    ws = make_ws(tmp_path)
    edit_xml(ws, "test_diag_log.xml", 'name="SR-011_numeric_parses"/>',
             'name="SR-011_numeric_parses"><error message="crash"/></testcase>')
    _, data = run(ws, GitFake())
    assert data["unexpected"] == ["test_diag_log::SR-011_numeric_parses"]


def test_base_only_case_passing_is_fixed(tmp_path):
    ws = make_ws(tmp_path)
    # base 목록에만 통과 케이스를 넣는다 → ⓑ. head 판 목록은 분류에 쓰지 않는다.
    _, data = run(ws, GitFake(BASE_TEXT + "test_diag_log::SR-011_numeric_parses\n"))
    assert data["fixed"] == ["test_diag_log::SR-011_numeric_parses"]
    assert data["unexpected"] == data["missing"] == []
    assert "test_diag_log::SR-011_numeric_parses" not in data["expected_head"]


def test_head_list_cannot_hide_failure(tmp_path):
    ws = make_ws(tmp_path)
    edit_xml(ws, "test_diag_log.xml", 'name="SR-011_numeric_parses"/>',
             'name="SR-011_numeric_parses"><failure message="boom"/></testcase>')
    head = ws / "tests" / "expected_failures.txt"
    head.write_text(head.read_text(encoding="utf-8") + "test_diag_log::SR-011_numeric_parses\n", encoding="utf-8")
    _, data = run(ws, GitFake())
    assert data["unexpected"] == ["test_diag_log::SR-011_numeric_parses"]


def test_base_case_absent_is_missing(tmp_path):
    ws = make_ws(tmp_path)
    _, data = run(ws, GitFake(BASE_TEXT + "test_diag_log::SR-999_gone\n"))
    assert data["missing"] == ["test_diag_log::SR-999_gone"]


def test_no_xml_is_error_exit0(tmp_path):
    ws = make_ws(tmp_path)
    for p in (ws / "test-results").glob("*.xml"):
        p.unlink()
    code, data = run(ws, GitFake(), stage="reverify")
    assert code == 0
    assert data["status"] == "error"
    assert "XML" in data["reason"]


def test_broken_xml_is_error(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "test-results" / "test_diag_log.xml").write_text("<testsuites><broken", encoding="utf-8")
    code, data = run(ws, GitFake())
    assert code == 0 and data["status"] == "error"


def test_zero_testcases_is_error(tmp_path):
    ws = make_ws(tmp_path)
    for p in (ws / "test-results").glob("*.xml"):
        p.write_text('<testsuites><testsuite name="s"/></testsuites>', encoding="utf-8")
    code, data = run(ws, GitFake())
    assert code == 0 and data["status"] == "error"


def test_git_show_failure_is_error(tmp_path):
    ws = make_ws(tmp_path)
    code, data = run(ws, GitFake(show_code=128))
    assert code == 0
    assert data["status"] == "error"
    assert "git show" in data["reason"]


def test_matches_check_junit_definitions(tmp_path):
    """vsm_test tests/check_junit.py judge() 의 정의를 식 수준으로 재현해 classify 와 대조한다:

        unexpected = [r for r in failed if r.ident not in expect]                    # ⓐ
        now_passing = sorted((expect & all_ids) - failed_ids)                        # ⓑ
        not_found = sorted(expect - all_ids)                                         # ⓒ
    """
    ws = make_ws(tmp_path)
    edit_xml(ws, "test_diag_log.xml", 'name="SR-011_numeric_parses"/>',
             'name="SR-011_numeric_parses"><failure message="boom"/></testcase>')
    outcomes = parse_results(ws / "test-results")
    # ⓐ: 목록에서 실패 하나를 빼고 통과 케이스 하나를 실패로 바꿈 · ⓑ: 통과 케이스 추가 · ⓒ: 없는 케이스 추가
    expect = set(parse_expect(BASE_TEXT + "test_sensor_filter::SR-007_average_exact\ntest_x::gone\n"))
    expect -= {"test_diag_log::SR-011_empty_returns_minus1"}

    all_ids = set(outcomes)
    failed_ids = {i for i, f in outcomes.items() if f}
    want_a = sorted(i for i in failed_ids if i not in expect)
    want_b = sorted((expect & all_ids) - failed_ids)
    want_c = sorted(expect - all_ids)

    got = classify(outcomes, sorted(expect))
    assert (got["unexpected"], got["fixed"], got["missing"]) == (want_a, want_b, want_c)
    assert len(want_a) == 2 and want_b and want_c  # 비어 있지 않은 분류로 비교했는지 확인
