# Step 2: junit-report

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-001: 표준 라이브러리만 (`xml.etree.ElementTree`)
- ADR-005: 에이전트 A는 실행된 테스트 실패를 근거로 판정

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `pr_reviewer/models.py` (TestFailure, TestReport 계약)
- `pr_reviewer/github.py` (`download_junit_reports`가 반환하는 XML 경로 목록이 이 step의 입력)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/junit.py`

```python
class JUnitParseError(Exception): ...

def parse_junit_files(paths: Sequence[Path]) -> TestReport:
    """여러 JUnit XML을 합쳐 TestReport(total, failures)로 반환."""
```

규칙:
- 루트가 `<testsuites>`이든 `<testsuite>`이든, 중첩 testsuite든 모든 `<testcase>`를 순회한다(`iter("testcase")`).
- `total` = testcase 수. `<failure>` 자식이 있으면 kind="failure", `<error>` 자식이 있으면 kind="error"인 `TestFailure`를 만든다. `<skipped>`는 total에만 포함한다.
- `message`는 요소의 `message` 속성, `details`는 요소 텍스트(없으면 ""). `name`/`classname`은 testcase 속성.
- `file`/`line`은 testcase 속성(`file`, `line`)이 있으면 쓴다. `line`이 정수가 아니면 None.
- `details`는 4000자로 자른다. 이유: 에이전트 프롬프트 크기 제한.
- XML 파싱 실패 파일은 `JUnitParseError`(파일 경로 포함)를 던진다. 호출 측(CLI)이 처리한다.
- 빈 `paths`이면 `TestReport(total=0, failures=())`.
- 외부 엔티티를 해석하지 않는다. `ElementTree` 기본 동작을 유지하고 `lxml` 등을 쓰지 마라.

### `tests/test_junit.py`
- `tmp_path`에 XML을 써서 테스트한다.
- 최소 케이스: pytest 형식(`<testsuites><testsuite>`), 단일 `<testsuite>` 루트, failure/error/skipped/pass 혼합, file/line 속성 유무, line 비정수, 여러 파일 합산, details 4000자 절단, 깨진 XML → JUnitParseError, 빈 목록.

## 요구사항 ID

R2

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/junit.py`
- `tests/test_junit.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_junit.py   # JUnit 파서 테스트 통과
py -m pytest -q                       # 전체 통과
py scripts/scope_check.py phases/0-mvp/step2.md   # 범위 이탈 없음
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

- 실패 테스트를 변경 라인에 매핑하는 로직을 여기에 넣지 마라. 이유: 매핑은 에이전트 A(step 4)의 책임이다.
- `models.py`, `github.py`를 수정하지 마라. 이유: 범위 밖.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
