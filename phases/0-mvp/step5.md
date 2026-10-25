# Step 5: aggregator

## 참조 문서

- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

## 근거 ADR

- ADR-005: 심각도 정책 (강등, 병합, review event, 자기 PR fallback, 추정 고지)
- ADR-003: 인라인은 commentable line에만 (범위 밖이면 GitHub 422)

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `pr_reviewer/models.py` (Finding, AgentResult, TestReport, InlineComment, ReviewPlan, SEVERITY_ORDER, CATEGORY_LABELS)
- `pr_reviewer/diff.py` (`parse_commentable_lines` 반환 형식 `dict[str, set[int]]`)
- `pr_reviewer/agents.py` (category별 Finding 생성 방식, A는 line=None 가능)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

### `pr_reviewer/aggregate.py`

```python
def apply_severity_rules(findings: Iterable[Finding]) -> list[Finding]:
    """ADR-005 등급 규칙을 적용한 새 Finding 목록 (dataclasses.replace)."""

def build_review_plan(pr: PullRequest, results: Sequence[AgentResult],
                      commentable: Mapping[str, set[int]], current_user: str,
                      report: TestReport | None) -> ReviewPlan: ...
```

`apply_severity_rules` (ADR-005, 순수 함수):
- `structural_test`
  - `line is not None` → `critical` (실행 근거).
  - `line is None` → `major`.
- `security`, `code_review`
  - `critical`: `reachability`가 비어 있으면 `major`로 강등한다. 그 뒤 `failure_scenario`가 비어 있으면 한 단계 더 내린다.
  - `major`: `failure_scenario`가 비어 있으면 `minor`로 강등한다.
  - `minor`는 그대로 둔다.
  - "비어 있음" = `strip()` 결과가 빈 문자열.

`build_review_plan` 규칙:
1. 모든 결과의 findings에 `apply_severity_rules`를 적용한다.
2. 인라인 후보 = `line is not None` 이고 `line in commentable.get(path, set())`인 finding. 나머지는 **요약 전용**으로 강등한다. CRITICAL 이유: 범위 밖 line이 하나라도 있으면 GitHub가 리뷰 전체를 422로 거부한다.
3. 인라인 후보를 `(path, line)`으로 묶어 `InlineComment` 하나로 병합한다.
   - 본문 첫 줄에는 그룹 내 최고 등급 배지(예: `**[CRITICAL]**`)를 둔다.
   - 그 아래에 각 finding을 `- [구조 기반 테스트] (major) 제목` + body + (있으면) failure_scenario 형식으로, 등급 순(SEVERITY_ORDER) → category 순서로 나열한다.
   - 결과 inline은 `(path, line)` 정렬.
4. event 결정 (등급 규칙 적용 후, 인라인/요약 전용 모두 포함한 critical 수 기준):
   - critical ≥ 1 이고 `pr.author != current_user` → `REQUEST_CHANGES`.
   - critical ≥ 1 이고 `pr.author == current_user` → `COMMENT`. 요약에 "Critical 있음(변경 요청 대상) — 자기 PR이라 COMMENT로 게시"를 표시한다.
   - critical 0 → `COMMENT`.
5. `review_body`: 한두 줄. 인라인 건수와 "요약은 PR 코멘트 참조"를 적는다. 빈 문자열 금지(GitHub는 코멘트 없는 COMMENT 리뷰에 body를 요구한다).
6. `summary_markdown`에 넣을 내용:
   - 제목 `## PR 리뷰 결과`.
   - 등급별 개수 표(Critical/Major/Minor × 관점 3종 + 합계).
   - 관점별 섹션(`### 구조 기반 테스트` / `### 보안` / `### 코드 리뷰`): finding을 등급 순으로 나열하고, 요약 전용 항목은 `path:line`(line 없으면 path)과 함께 적는다. 해당 관점이 skipped면 사유를, error면 "실행 실패: <error>"를 적는다.
   - 구조 기반 테스트 섹션에는 `report`가 있으면 "총 N건 중 실패 M건"을 적는다.
   - 보안·코드 리뷰 섹션 끝에 고지 "정적 분석 기반 추정 등급이며 실행 검증이 아닙니다."를 넣는다.
   - 자기 PR critical 표시(4번).

### `tests/test_aggregate.py`
- 최소 케이스:
  - 등급 규칙: A line 유/무, B/C critical에서 reachability 없음 → major, critical에서 둘 다 없음 → minor, major에서 scenario 없음 → minor, 공백만 있는 문자열도 빈 값으로 취급
  - diff 밖 line, 파일 자체가 diff에 없음, line None → 요약 전용으로 가고 inline에 없음
  - 같은 path+line에 A/B/C 지적 → InlineComment 1개, 최고 등급 배지, 라벨 3종
  - event: 타인 PR + critical → REQUEST_CHANGES, 자기 PR + critical → COMMENT + 요약 표시, critical 0 → COMMENT
  - 요약 전용 critical도 event 판정에 포함
  - skipped/error 사유가 요약에 표시됨, report 건수 표시, 추정 고지 포함
  - review_body가 비어 있지 않음

## 요구사항 ID

R4, R5

## 변경 허용 범위

이 목록 밖의 파일은 수정하지 마라. scope_check.py가 검사한다.

- `pr_reviewer/aggregate.py`
- `tests/test_aggregate.py`

## Acceptance Criteria

```bash
py -m pytest -q tests/test_aggregate.py   # 취합·심각도 테스트 통과
py -m pytest -q                           # 전체 통과
py scripts/scope_check.py phases/0-mvp/step5.md   # 범위 이탈 없음
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

- `APPROVE` event를 만들지 마라. 이유: 리뷰어가 머지를 승인하는 것은 MVP 범위 밖이며 위험하다.
- I/O(gh 호출, 파일 쓰기)를 넣지 마라. 이유: ARCHITECTURE 패턴 — aggregate는 순수 로직.
- ADR-005에 없는 등급 규칙(예: 중복 지적 수에 따른 승격)을 추가하지 마라. 이유: 승인된 정책만 구현.
- 기존 테스트를 깨뜨리지 마라
- AC에 없는 기능, 리팩터링, 의존성을 추가하지 마라. 이유: MVP 범위 고정. 아이디어는 `docs/PROPOSALS.md`에 `[ ]` 항목으로만 기록하라.
