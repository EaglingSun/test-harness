# Step 0: diff-parser

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-001: Python 3.13 표준 라이브러리 + pytest, 루트 `pr_reviewer/` 패키지
- ADR-003: 인라인 코멘트는 diff RIGHT side line에만 (범위 밖이면 GitHub 422)
- ADR-004: 외부 호출은 runner 주입 (`proc.py`)
- ADR-005: 심각도 3단계, category 3종

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `docs/ARCHITECTURE.md` (디렉토리 구조, 데이터 흐름)
- `docs/ADR.md` (ADR-001~005)
- `.gitignore`, 기존 `scripts/test_*.py` (pytest 실행 방식 확인. 이 테스트들도 `py -m pytest -q`에 포함되어 계속 통과해야 한다)

이 step이 첫 step이다. 이후 모든 step이 이 step의 `models.py`와 `proc.py` 계약을 그대로 쓴다.

## 작업

### 1. `pyproject.toml`
- `[tool.pytest.ini_options]`에 `pythonpath = ["."]`만 둔다. `testpaths`는 설정하지 마라(기존 `scripts/test_*.py`가 계속 수집되어야 한다).
- 빌드 시스템·의존성 섹션은 넣지 마라.

### 2. `pr_reviewer/__init__.py`
- 빈 파일 또는 docstring 한 줄.

### 3. `pr_reviewer/models.py` — 모듈 간 계약 (이 이름·필드를 그대로 쓴다)

```python
Severity = Literal["critical", "major", "minor"]
Category = Literal["structural_test", "security", "code_review"]
SEVERITY_ORDER: dict[str, int]   # critical=0, major=1, minor=2 (정렬·비교용)
CATEGORY_LABELS: dict[str, str]  # structural_test="구조 기반 테스트", security="보안", code_review="코드 리뷰"

@dataclass(frozen=True)
class PullRequest:
    owner: str; repo: str; number: int
    head_sha: str; author: str; url: str

@dataclass(frozen=True)
class Finding:
    category: Category
    path: str
    line: int | None          # None = 라인 특정 불가 → 요약에만 기록
    severity: Severity
    title: str
    body: str
    failure_scenario: str = ""  # 입력 → 기대 vs 실제
    reachability: str = ""      # 정상 호출 흐름에서 도달 가능한 근거

@dataclass(frozen=True)
class TestFailure:
    name: str; classname: str
    kind: Literal["failure", "error"]
    message: str; details: str
    file: str | None = None; line: int | None = None

@dataclass(frozen=True)
class TestReport:
    total: int                     # 실행된 testcase 수 (skipped 포함)
    failures: tuple[TestFailure, ...]

@dataclass(frozen=True)
class AgentResult:
    category: Category
    findings: tuple[Finding, ...] = ()
    error: str | None = None          # 에이전트 실행 실패 사유
    skipped_reason: str | None = None # 실행하지 않은 사유 (예: 테스트 결과 없음)

@dataclass(frozen=True)
class InlineComment:
    path: str; line: int; body: str

@dataclass(frozen=True)
class ReviewPlan:
    event: Literal["COMMENT", "REQUEST_CHANGES"]
    review_body: str
    inline: tuple[InlineComment, ...]
    summary_markdown: str
```
- `TestFailure`, `TestReport`는 pytest가 테스트 클래스로 수집하려 할 수 있다. 각 클래스에 `__test__ = False`를 둬 수집 경고를 막아라(dataclass 필드가 아닌 ClassVar로).

### 4. `pr_reviewer/proc.py` — Runner 계약

```python
Runner = Callable[[list[str], str | None], subprocess.CompletedProcess]

def run_process(args: list[str], input: str | None = None, timeout: float = 900) -> subprocess.CompletedProcess:
    """shell=False, capture_output, text, encoding='utf-8', errors='replace', check=False."""
```
- 이 step에서는 `run_process`를 실제로 호출하는 테스트를 쓰지 마라(CLAUDE.md CRITICAL: 테스트에서 실제 외부 프로세스 금지). 시그니처만 존재하면 된다.

### 5. `pr_reviewer/diff.py`

```python
def parse_commentable_lines(diff_text: str) -> dict[str, set[int]]:
    """`gh pr diff` 형식의 unified diff → {새 파일 경로: RIGHT side에서 코멘트 가능한 줄 번호 집합}."""
```
규칙:
- 경로는 `+++ b/<path>`의 `<path>`를 쓴다(rename이면 새 경로). `+++ /dev/null`(삭제 파일)은 결과에 넣지 않는다.
- hunk 헤더 `@@ -a,b +c,d @@`의 `c`부터 새 파일 줄 번호를 센다. `+` 줄과 ` `(context) 줄은 집합에 넣고 번호를 증가시킨다. `-` 줄은 번호를 증가시키지 않는다. `\ No newline at end of file`은 무시한다.
- hunk 헤더의 `,d` 생략형(`+c`)도 처리한다.
- binary 파일(`Binary files ... differ`)은 hunk가 없으므로 결과에 넣지 않는다.
- CRLF가 섞여도 동작해야 한다.

### 6. `tests/test_diff.py`
최소 케이스: 단일 hunk 추가, 여러 hunk, 여러 파일, 삭제 줄이 섞인 hunk의 번호 계산, 신규 파일(`--- /dev/null`), 삭제 파일(`+++ /dev/null`), rename, `,d` 생략형, `\ No newline`, binary, CRLF.

## 요구사항 ID

R1

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pyproject.toml`
- `pr_reviewer/__init__.py`
- `pr_reviewer/models.py`
- `pr_reviewer/proc.py`
- `pr_reviewer/diff.py`
- `tests/test_diff.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_diff.py   # diff 파서 테스트 통과
py -m pytest -q                      # 기존 scripts 테스트 포함 전체 통과
py -c "from pr_reviewer.models import PullRequest, Finding, TestFailure, TestReport, AgentResult, InlineComment, ReviewPlan, SEVERITY_ORDER, CATEGORY_LABELS; from pr_reviewer.proc import Runner, run_process"
py scripts/scope_check.py phases/0-mvp/step0.md   # 범위 이탈 없음
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - CLAUDE.md CRITICAL 규칙을 위반하지 않았는가?
   - "근거 ADR"의 결정을 따랐는가? 새 기술 결정이 필요했다면 구현하지 말고 blocked 처리하라.
3. 결과에 따라 `phases/0-mvp/index.json`의 해당 step을 업데이트한다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약"`
   - 수정 3회 시도 후에도 실패 → `"status": "error"`, `"error_message": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"blocked_reason": "구체적 사유"` 후 즉시 중단

## 금지사항

- `models.py`의 클래스명·필드명·타입을 위 계약과 다르게 만들지 마라. 이유: 이후 step 1~6이 이 계약을 그대로 가정한다.
- 외부 패키지(unidiff 등)를 쓰지 마라. 이유: ADR-001.
- `pyproject.toml`에 `testpaths`를 넣지 마라. 이유: 기존 scripts 테스트가 수집에서 빠진다.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
