"""심각도 규칙(ADR-005), 같은 path+line 병합, diff 밖 요약 강등, review event 결정, markdown 요약 (R4, R5). I/O 없음."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from pr_reviewer.models import (
    CATEGORY_LABELS,
    SEVERITY_ORDER,
    AgentResult,
    Finding,
    InlineComment,
    PullRequest,
    ReviewPlan,
    TestReport,
)

_CATEGORY_ORDER = {c: i for i, c in enumerate(CATEGORY_LABELS)}
_STATIC_CATEGORIES = ("security", "code_review")
_DOWNGRADE = {"critical": "major", "major": "minor", "minor": "minor"}
_SEVERITY_NAMES = {"critical": "Critical", "major": "Major", "minor": "Minor"}

STATIC_DISCLAIMER = "정적 분석 기반 추정 등급이며 실행 검증이 아닙니다."
OWN_PR_CRITICAL = "Critical 있음(변경 요청 대상) — 자기 PR이라 COMMENT로 게시"


def _blank(text: str) -> bool:
    return not text.strip()


def _rated(finding: Finding) -> Finding:
    if finding.category == "structural_test":
        return replace(finding, severity="critical" if finding.line is not None else "major")
    severity = finding.severity
    if severity == "critical" and _blank(finding.reachability):
        severity = "major"
        if _blank(finding.failure_scenario):
            severity = _DOWNGRADE[severity]
    elif severity in ("critical", "major") and _blank(finding.failure_scenario):
        severity = _DOWNGRADE[severity]
    return replace(finding, severity=severity)


def apply_severity_rules(findings: Iterable[Finding]) -> list[Finding]:
    """ADR-005 등급 규칙을 적용한 새 Finding 목록 (dataclasses.replace)."""
    return [_rated(f) for f in findings]


def _sort_key(finding: Finding) -> tuple[int, int]:
    return SEVERITY_ORDER[finding.severity], _CATEGORY_ORDER[finding.category]


def _location(finding: Finding) -> str:
    return finding.path if finding.line is None else f"{finding.path}:{finding.line}"


def _render_inline(group: list[Finding]) -> str:
    group = sorted(group, key=_sort_key)
    lines = [f"**[{group[0].severity.upper()}]**"]
    for f in group:
        lines.append(f"- [{CATEGORY_LABELS[f.category]}] ({f.severity}) {f.title}")
        lines.append(f"  {f.body}")
        if not _blank(f.failure_scenario):
            lines.append(f"  - 실패 시나리오: {f.failure_scenario}")
    return "\n".join(lines)


def _render_summary(results: Sequence[AgentResult], rated: list[Finding], summary_only: set[int],
                    report: TestReport | None, own_pr_critical: bool) -> str:
    out = ["## PR 리뷰 결과", ""]
    if own_pr_critical:
        out += [f"> **{OWN_PR_CRITICAL}**", ""]

    categories = list(CATEGORY_LABELS)
    out.append("| 등급 | " + " | ".join(CATEGORY_LABELS[c] for c in categories) + " | 합계 |")
    out.append("|---" * (len(categories) + 2) + "|")
    for severity, name in _SEVERITY_NAMES.items():
        counts = [sum(1 for f in rated if f.category == c and f.severity == severity) for c in categories]
        out.append(f"| {name} | " + " | ".join(map(str, counts)) + f" | {sum(counts)} |")

    by_category = {r.category: r for r in results}
    for category in categories:
        out += ["", f"### {CATEGORY_LABELS[category]}"]
        result = by_category.get(category)
        if category == "structural_test" and report is not None:
            out.append(f"총 {report.total}건 중 실패 {len(report.failures)}건")
        if result is not None and result.error:
            out.append(f"실행 실패: {result.error}")
        elif result is not None and result.skipped_reason:
            out.append(f"실행하지 않음: {result.skipped_reason}")
        items = sorted(((i, f) for i, f in enumerate(rated) if f.category == category),
                       key=lambda pair: _sort_key(pair[1]))
        if not items and not (result and (result.error or result.skipped_reason)):
            out.append("지적 없음")
        for i, f in items:
            if i in summary_only:
                out.append(f"- ({f.severity}) {f.title} — `{_location(f)}` (요약 전용)")
                out.append(f"  {f.body}")
                if not _blank(f.failure_scenario):
                    out.append(f"  - 실패 시나리오: {f.failure_scenario}")
            else:
                out.append(f"- ({f.severity}) {f.title} — `{_location(f)}` (인라인)")
        if category in _STATIC_CATEGORIES:
            out += ["", f"_{STATIC_DISCLAIMER}_"]
    return "\n".join(out) + "\n"


def build_review_plan(pr: PullRequest, results: Sequence[AgentResult],
                      commentable: Mapping[str, set[int]], current_user: str,
                      report: TestReport | None) -> ReviewPlan:
    rated = apply_severity_rules(f for r in results for f in r.findings)

    groups: dict[tuple[str, int], list[Finding]] = {}
    summary_only: set[int] = set()
    for i, f in enumerate(rated):
        # 범위 밖 line이 하나라도 있으면 GitHub가 리뷰 전체를 422로 거부한다 → 요약 전용으로 강등.
        if f.line is not None and f.line in commentable.get(f.path, set()):
            groups.setdefault((f.path, f.line), []).append(f)
        else:
            summary_only.add(i)
            # ADR-005: 변경 라인 매핑 근거가 없는 A 실패는 요약 전용 major.
            if f.category == "structural_test":
                rated[i] = replace(f, severity="major")
    inline = tuple(InlineComment(path=path, line=line, body=_render_inline(groups[(path, line)]))
                   for path, line in sorted(groups))

    has_critical = any(f.severity == "critical" for f in rated)
    own_pr = pr.author == current_user
    event = "REQUEST_CHANGES" if has_critical and not own_pr else "COMMENT"

    review_body = f"pr-reviewer: 인라인 코멘트 {len(inline)}건. 요약은 PR 코멘트 참조."
    summary = _render_summary(results, rated, summary_only, report, has_critical and own_pr)
    return ReviewPlan(event=event, review_body=review_body, inline=inline, summary_markdown=summary)
