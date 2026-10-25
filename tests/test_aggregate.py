"""aggregate.py 테스트 — 심각도 규칙(ADR-005), 병합, diff 밖 강등, event 결정, 요약 렌더링. I/O 없음."""

import pytest

from pr_reviewer.aggregate import apply_severity_rules, build_review_plan
from pr_reviewer.models import AgentResult, Finding, PullRequest, TestFailure, TestReport

PR = PullRequest(owner="o", repo="r", number=7, head_sha="abc123", author="dev",
                 url="https://github.com/o/r/pull/7")
COMMENTABLE = {"app.py": {1, 2, 3}, "lib.py": {10}}


def f(category="security", severity="major", path="app.py", line=2, title="제목",
      body="본문", failure_scenario="입력 → 기대 vs 실제", reachability="main → handler") -> Finding:
    return Finding(category=category, path=path, line=line, severity=severity, title=title,
                   body=body, failure_scenario=failure_scenario, reachability=reachability)


def plan(*results, user="reviewer", report=None, commentable=COMMENTABLE):
    return build_review_plan(PR, list(results), commentable, user, report)


# --- apply_severity_rules ---

def test_structural_with_line_is_critical():
    [out] = apply_severity_rules([f("structural_test", "minor", line=2)])
    assert out.severity == "critical"


def test_structural_without_line_is_major():
    [out] = apply_severity_rules([f("structural_test", "critical", line=None)])
    assert out.severity == "major"


@pytest.mark.parametrize("category", ["security", "code_review"])
def test_critical_without_reachability_becomes_major(category):
    [out] = apply_severity_rules([f(category, "critical", reachability="")])
    assert out.severity == "major"


@pytest.mark.parametrize("category", ["security", "code_review"])
def test_critical_without_both_becomes_minor(category):
    [out] = apply_severity_rules([f(category, "critical", reachability="", failure_scenario="")])
    assert out.severity == "minor"


def test_critical_without_scenario_becomes_major():
    [out] = apply_severity_rules([f("security", "critical", failure_scenario="")])
    assert out.severity == "major"


@pytest.mark.parametrize("category", ["security", "code_review"])
def test_major_without_scenario_becomes_minor(category):
    [out] = apply_severity_rules([f(category, "major", failure_scenario="")])
    assert out.severity == "minor"


def test_whitespace_only_counts_as_empty():
    [out] = apply_severity_rules([f("code_review", "critical", reachability="  \n\t",
                                    failure_scenario="   ")])
    assert out.severity == "minor"


def test_complete_evidence_keeps_severity_and_minor_unchanged():
    out = apply_severity_rules([f("security", "critical"), f("code_review", "minor", failure_scenario="")])
    assert [x.severity for x in out] == ["critical", "minor"]


def test_apply_returns_new_objects_without_mutating_input():
    src = f("security", "critical", reachability="")
    [out] = apply_severity_rules([src])
    assert src.severity == "critical" and out is not src


# --- inline 후보 / 요약 전용 강등 ---

def test_out_of_diff_lines_go_to_summary_only():
    findings = (
        f(line=99, title="diff 밖 라인"),
        f(path="other.py", line=1, title="diff에 없는 파일"),
        f(line=None, title="라인 없음"),
        f(line=3, title="인라인 대상"),
    )
    p = plan(AgentResult(category="security", findings=findings))
    assert [(c.path, c.line) for c in p.inline] == [("app.py", 3)]
    assert "인라인 대상" in p.inline[0].body
    for title, loc in [("diff 밖 라인", "app.py:99"), ("diff에 없는 파일", "other.py:1"),
                       ("라인 없음", "app.py")]:
        assert title in p.summary_markdown
        assert loc in p.summary_markdown
        assert all(title not in c.body for c in p.inline)


def test_inline_sorted_by_path_and_line():
    findings = (f(path="lib.py", line=10), f(line=3), f(line=1))
    p = plan(AgentResult(category="code_review", findings=findings))
    assert [(c.path, c.line) for c in p.inline] == [("app.py", 1), ("app.py", 3), ("lib.py", 10)]


# --- 병합 ---

def test_same_path_line_merged_with_highest_badge_and_three_labels():
    p = plan(
        AgentResult(category="security", findings=(f("security", "major", title="보안 지적"),)),
        AgentResult(category="code_review",
                    findings=(f("code_review", "major", title="코드 지적", failure_scenario=""),)),
        AgentResult(category="structural_test",
                    findings=(f("structural_test", "minor", title="테스트 지적"),)),
    )
    assert len(p.inline) == 1
    body = p.inline[0].body
    assert body.splitlines()[0] == "**[CRITICAL]**"
    i_a = body.index("- [구조 기반 테스트] (critical) 테스트 지적")
    i_b = body.index("- [보안] (major) 보안 지적")
    i_c = body.index("- [코드 리뷰] (minor) 코드 지적")
    assert i_a < i_b < i_c
    assert "입력 → 기대 vs 실제" in body


def test_same_severity_ordered_by_category():
    p = plan(
        AgentResult(category="code_review", findings=(f("code_review", "major", title="C"),)),
        AgentResult(category="security", findings=(f("security", "major", title="B"),)),
    )
    body = p.inline[0].body
    assert body.splitlines()[0] == "**[MAJOR]**"
    assert body.index("[보안] (major) B") < body.index("[코드 리뷰] (major) C")


# --- event ---

def test_other_author_with_critical_requests_changes():
    p = plan(AgentResult(category="security", findings=(f("security", "critical"),)), user="reviewer")
    assert p.event == "REQUEST_CHANGES"
    assert "자기 PR" not in p.summary_markdown


def test_own_pr_with_critical_falls_back_to_comment():
    p = plan(AgentResult(category="security", findings=(f("security", "critical"),)), user="dev")
    assert p.event == "COMMENT"
    assert "Critical 있음(변경 요청 대상) — 자기 PR이라 COMMENT로 게시" in p.summary_markdown


def test_no_critical_is_comment():
    p = plan(AgentResult(category="security", findings=(f("security", "critical", reachability=""),)))
    assert p.event == "COMMENT"


def test_summary_only_critical_counts_for_event():
    p = plan(AgentResult(category="security", findings=(f("security", "critical", line=99),)))
    assert p.inline == ()
    assert p.event == "REQUEST_CHANGES"


def test_never_approve():
    p = plan()
    assert p.event in ("COMMENT", "REQUEST_CHANGES")


# --- summary / review_body ---

def test_summary_shows_skipped_error_report_and_disclaimer():
    report = TestReport(total=12, failures=(
        TestFailure(name="t", classname="c", kind="failure", message="m", details="d"),))
    p = plan(
        AgentResult(category="structural_test", skipped_reason="테스트 결과 없음"),
        AgentResult(category="security", error="timeout"),
        AgentResult(category="code_review"),
        report=report,
    )
    s = p.summary_markdown
    assert s.startswith("## PR 리뷰 결과")
    for section in ("### 구조 기반 테스트", "### 보안", "### 코드 리뷰"):
        assert section in s
    assert "테스트 결과 없음" in s
    assert "실행 실패: timeout" in s
    assert "총 12건 중 실패 1건" in s
    assert s.count("정적 분석 기반 추정 등급이며 실행 검증이 아닙니다.") == 2


def test_summary_count_table():
    p = plan(
        AgentResult(category="structural_test", findings=(f("structural_test", line=2),)),
        AgentResult(category="security",
                    findings=(f("security", "major"), f("security", "major", failure_scenario=""))),
        AgentResult(category="code_review", findings=(f("code_review", "minor"),)),
    )
    s = p.summary_markdown
    assert "| 등급 | 구조 기반 테스트 | 보안 | 코드 리뷰 | 합계 |" in s
    assert "| Critical | 1 | 0 | 0 | 1 |" in s
    assert "| Major | 0 | 1 | 0 | 1 |" in s
    assert "| Minor | 0 | 1 | 1 | 2 |" in s


def test_summary_lists_findings_by_severity():
    p = plan(AgentResult(category="code_review", findings=(
        f("code_review", "minor", title="작은 것"), f("code_review", "critical", title="큰 것"))))
    s = p.summary_markdown
    assert s.index("큰 것") < s.index("작은 것")


@pytest.mark.parametrize("results", [
    (),
    (AgentResult(category="security", findings=(f(line=2),)),),
])
def test_review_body_not_empty_and_mentions_inline_count(results):
    p = plan(*results)
    assert p.review_body.strip()
    assert f"인라인 코멘트 {len(p.inline)}건" in p.review_body
    assert "요약은 PR 코멘트 참조" in p.review_body
