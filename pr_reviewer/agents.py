"""리뷰 에이전트 A/B/C: 프롬프트, findings schema, category 필터 (R3, ADR-002, ADR-005)."""

from pr_reviewer.models import AgentResult, Finding, PullRequest, TestReport
from pr_reviewer.proc import Runner, run_process
from pr_reviewer.runner import run_claude, run_parallel

FINDINGS_SCHEMA: dict = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "path", "line", "severity", "title", "body",
                             "failure_scenario", "reachability"],
                "properties": {
                    "category": {"enum": ["structural_test", "security", "code_review"]},
                    "path": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "severity": {"enum": ["critical", "major", "minor"]},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "failure_scenario": {"type": "string"},
                    "reachability": {"type": "string"},
                },
            },
        },
    },
}

NO_TOOLS = ["Bash", "Edit", "Write"]
CODE_REVIEW_ALLOWED_TOOLS = ["Bash(gh pr diff:*)", "Bash(gh pr view:*)"]  # gh api는 POST 게시 가능 → 제외

SEVERITY_RULES = """## 심각도 등급 (ADR-005)
- critical: 정상 사용 경로에서 크래시·데이터 손상·보안 침해가 확정적으로 발생한다.
- major: 특정 조건(경계값, 특정 동등분할 클래스, 조건부 악용 경로)에서만 오동작한다.
- minor: 현재 결함은 아니나 방어 부족, 하드닝 제안이다.

## 근거 규칙
- critical/major는 failure_scenario(입력 → 기대 vs 실제)를 반드시 채운다. 비어 있으면 한 단계 강등된다.
- critical은 reachability(정상 호출 흐름에서 도달 가능한 근거)를 반드시 채운다. 비어 있으면 major로 강등된다.
"""

LOCATION_RULES = """## 위치 규칙
- path는 diff의 새 파일 경로(+++ b/ 쪽), line은 새 파일 기준 줄 번호다.
- 줄을 특정할 근거가 없으면 line을 null로 둔다.
"""

_STR_FIELDS = ("path", "title", "body", "failure_scenario", "reachability")
_SEVERITIES = ("critical", "major", "minor")


def _to_findings(output: dict, category: str) -> tuple[Finding, ...]:
    """structured_output → Finding. 다른 category, 필수 필드 누락, 타입 오류 item은 버린다."""
    items = output.get("findings")
    if not isinstance(items, list):
        return ()
    findings = []
    for item in items:
        if not isinstance(item, dict) or item.get("category") != category:
            continue
        if not all(isinstance(item.get(k), str) for k in _STR_FIELDS) or not item["path"]:
            continue
        line = item.get("line", ...)
        if line is not None and (type(line) is not int or line < 1):
            continue
        if item.get("severity") not in _SEVERITIES:
            continue
        findings.append(Finding(
            category=category, path=item["path"], line=line, severity=item["severity"],
            title=item["title"], body=item["body"],
            failure_scenario=item["failure_scenario"], reachability=item["reachability"],
        ))
    return tuple(findings)


def _format_failures(report: TestReport) -> str:
    blocks = []
    for i, f in enumerate(report.failures, 1):
        blocks.append(
            f"### 실패 {i}\n"
            f"- name: {f.name}\n- classname: {f.classname}\n- kind: {f.kind}\n"
            f"- message: {f.message}\n- file: {f.file or '(없음)'}\n"
            f"- line: {f.line if f.line is not None else '(없음)'}\n"
            f"- details:\n```\n{f.details}\n```"
        )
    return "\n\n".join(blocks)


def review_structural_tests(pr: PullRequest, diff: str, report: TestReport | None,
                            runner: Runner = run_process) -> AgentResult:
    """에이전트 A: CI 테스트 실패를 변경 코드 위치에 매핑한다. 실패 0건이면 claude를 호출하지 않는다."""
    if report is None:
        return AgentResult(category="structural_test", skipped_reason="테스트 결과 없음")
    if not report.failures:
        return AgentResult(category="structural_test",
                           skipped_reason=f"실패 테스트 0건 (총 {report.total}건)")

    prompt = f"""당신은 '구조 기반 테스트' 관점의 PR 리뷰어다. PR: {pr.url}
아래 diff와 CI에서 실패한 테스트 목록을 보고, 각 실패의 원인이 된 **변경 코드** 위치를 찾아라.

## 지시
- 관점은 로직 오류, 예외 처리 누락, 경계값, 동등분할이다. 아래 실패들 외의 문제는 보고하지 마라.
- 각 실패의 원인이 된 변경 코드 위치를 path/line으로 적어라. 근거가 없으면 line을 null로 둔다.
- failure_scenario에는 테스트 이름과 실패 메시지를 적어라.
- category는 항상 "structural_test"로 둔다.
- 도구를 쓰지 말고 주어진 정보만으로 답하라.

{LOCATION_RULES}
{SEVERITY_RULES}
## 실패 테스트 (총 {report.total}건 중 {len(report.failures)}건 실패)
{_format_failures(report)}

## diff
```diff
{diff}
```
"""
    output = run_claude(prompt, schema=FINDINGS_SCHEMA, disallowed_tools=NO_TOOLS, runner=runner)
    return AgentResult(category="structural_test", findings=_to_findings(output, "structural_test"))


def review_security(pr: PullRequest, diff: str, runner: Runner = run_process) -> AgentResult:
    """에이전트 B: diff의 보안 결함만 정적 분석한다."""
    prompt = f"""당신은 '보안' 관점의 PR 리뷰어다. PR: {pr.url}
아래 diff의 변경 코드에서 보안 결함을 찾아라.

## 지시
- 관점은 injection, 인증·인가 누락, 시크릿 노출, 안전하지 않은 입력 처리다.
- 보안 외 문제는 보고하지 마라.
- category는 항상 "security"로 둔다.
- 결함이 없으면 빈 findings를 반환한다.
- 도구를 쓰지 말고 주어진 diff만으로 답하라.

{LOCATION_RULES}
{SEVERITY_RULES}
## diff
```diff
{diff}
```
"""
    output = run_claude(prompt, schema=FINDINGS_SCHEMA, disallowed_tools=NO_TOOLS, runner=runner)
    return AgentResult(category="security", findings=_to_findings(output, "security"))


def review_code(pr: PullRequest, runner: Runner = run_process) -> AgentResult:
    """에이전트 C: /code-review 텍스트 리뷰(1단계)를 findings JSON으로 변환(2단계)한다. 보안 지적은 제외."""
    # --comment/--fix는 넣지 않는다: 스킬이 직접 게시·수정하면 취합 단계를 건너뛴다.
    review_text = run_claude(None, args_prompt=f"/code-review low {pr.url}",
                             allowed_tools=CODE_REVIEW_ALLOWED_TOOLS,
                             disallowed_tools=["Edit", "Write"], runner=runner)

    prompt = f"""아래는 PR {pr.url} 에 대한 코드 리뷰 텍스트다. 이 텍스트의 지적을 findings JSON으로 옮겨라.

## 지시
- category는 항상 "code_review"로 둔다.
- 보안 관련 지적(injection, 인증·인가, 시크릿 노출, 안전하지 않은 입력 처리 등)은 제외한다.
- 새 지적을 만들지 마라. 텍스트에 있는 지적만 옮긴다.
- 리뷰 결과가 "(none)"처럼 지적이 없으면 빈 findings를 반환한다.
- 텍스트에 있는 실패 시나리오와 도달 경로를 failure_scenario, reachability에 옮겨라. 없으면 빈 문자열로 둔다.

{LOCATION_RULES}
{SEVERITY_RULES}
## 코드 리뷰 텍스트
{review_text}
"""
    output = run_claude(prompt, schema=FINDINGS_SCHEMA, disallowed_tools=NO_TOOLS, runner=runner)
    return AgentResult(category="code_review", findings=_to_findings(output, "code_review"))


def run_all_agents(pr: PullRequest, diff: str, report: TestReport | None,
                   runner: Runner = run_process) -> list[AgentResult]:
    """run_parallel({"structural_test":..., "security":..., "code_review":...}) 결과를 반환."""
    return run_parallel({
        "structural_test": lambda: review_structural_tests(pr, diff, report, runner),
        "security": lambda: review_security(pr, diff, runner),
        "code_review": lambda: review_code(pr, runner),
    })
