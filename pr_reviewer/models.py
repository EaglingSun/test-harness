"""모듈 간 계약 dataclass. 모듈 경계는 이 타입으로만 주고받는다."""

from dataclasses import dataclass
from typing import ClassVar, Literal

Severity = Literal["critical", "major", "minor"]
Category = Literal["structural_test", "security", "code_review"]

SEVERITY_ORDER: dict[str, int] = {"critical": 0, "major": 1, "minor": 2}
CATEGORY_LABELS: dict[str, str] = {
    "structural_test": "구조 기반 테스트",
    "security": "보안",
    "code_review": "코드 리뷰",
}


@dataclass(frozen=True)
class PullRequest:
    owner: str
    repo: str
    number: int
    head_sha: str
    author: str
    url: str


@dataclass(frozen=True)
class Finding:
    category: Category
    path: str
    line: int | None  # None = 라인 특정 불가 → 요약에만 기록
    severity: Severity
    title: str
    body: str
    failure_scenario: str = ""  # 입력 → 기대 vs 실제
    reachability: str = ""  # 정상 호출 흐름에서 도달 가능한 근거


@dataclass(frozen=True)
class TestFailure:
    __test__: ClassVar[bool] = False  # pytest 수집 방지

    name: str
    classname: str
    kind: Literal["failure", "error"]
    message: str
    details: str
    file: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class TestReport:
    __test__: ClassVar[bool] = False  # pytest 수집 방지

    total: int  # 실행된 testcase 수 (skipped 포함)
    failures: tuple[TestFailure, ...]


@dataclass(frozen=True)
class AgentResult:
    category: Category
    findings: tuple[Finding, ...] = ()
    error: str | None = None  # 에이전트 실행 실패 사유
    skipped_reason: str | None = None  # 실행하지 않은 사유 (예: 테스트 결과 없음)


@dataclass(frozen=True)
class InlineComment:
    path: str
    line: int
    body: str


@dataclass(frozen=True)
class ReviewPlan:
    event: Literal["COMMENT", "REQUEST_CHANGES"]
    review_body: str
    inline: tuple[InlineComment, ...]
    summary_markdown: str
