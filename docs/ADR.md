# Architecture Decision Records

> 규칙
> - 각 ADR은 `**Status**: Proposed | Accepted | Superseded by ADR-NNN` 중 하나를 가진다.
> - step은 Accepted ADR만 `## 근거 ADR`에 참조한다. 결정을 바꿀 때는 기존 ADR을 수정하지 말고 새 ADR을 추가한 뒤 기존 ADR을 Superseded로 표시한다.
> - ADR 추가와 Status 변경은 phase 설계 시점에 Human 승인으로만 한다.

## 철학
MVP 속도 최우선. 외부 패키지 없이 이미 설치·인증된 CLI(`gh`, `claude`)를 재사용한다. 리뷰 결과의 신뢰도를 등급과 고지로 정직하게 드러낸다.

---

### ADR-001: Python 3.13 표준 라이브러리 + pytest
**Status**: Accepted
**결정**: 구현은 Python 3.13 표준 라이브러리만 사용한다(`subprocess`, `json`, `xml.etree`, `concurrent.futures`, `argparse`, `dataclasses`, `tempfile`). 테스트는 pytest. 패키지 구조는 루트의 `pr_reviewer/`, 실행은 `py -m pr_reviewer`.
**이유**: 하네스 VERIFY가 `pytest -q`이고, 새 의존성 없이 바로 실행 가능하다.
**트레이드오프**: HTTP 클라이언트·GitHub SDK의 편의 기능을 포기한다.

### ADR-002: 리뷰 엔진은 claude CLI headless, 3개 에이전트 병렬
**Status**: Accepted
**결정**:
- 에이전트 A(구조 기반 테스트), B(보안)는 `claude -p <prompt> --output-format json --json-schema <schema>`로 실행하고 결과 JSON의 `structured_output`을 읽는다. diff와 테스트 실패는 프롬프트로 전달하고 도구는 쓰지 않게 한다(`--disallowedTools Bash Edit Write`).
- 에이전트 C(코드 리뷰)는 2단계다. (1) `claude -p "/code-review low <PR URL>" --output-format json --allowedTools "Bash(gh pr diff:*)" "Bash(gh pr view:*)" --disallowedTools Edit Write`로 텍스트 리뷰를 받는다. (2) 그 텍스트를 `claude -p ... --json-schema`로 findings JSON으로 변환한다. 변환 단계에서 보안 지적은 제외한다(B와 관점 분리).
- 3개 에이전트는 `concurrent.futures.ThreadPoolExecutor`로 병렬 실행한다. 하나가 실패(비정상 종료, JSON 파싱 실패, timeout)해도 나머지 결과로 진행하고 실패 사실을 결과에 남긴다.
- 프로세스는 셸 없이 인자 리스트로 실행한다(`shell=False`).
- 프롬프트는 명령 인자가 아니라 **stdin**으로 전달한다(`claude -p --output-format json ...`에 stdin 입력). 이유: Windows 명령줄 길이 제한(~32k자)을 diff가 넘을 수 있다. 단 C의 1단계 `/code-review low <PR URL>`은 짧으므로 인자로 전달한다.
**이유**: 2026-10-25 스파이크에서 확인 — `/code-review`는 headless에서 동작하지만 `--json-schema`를 무시하고 텍스트로만 답한다. PR URL 인자 + 위 allowedTools 조합이면 대상 repo checkout 없이 동작한다. `/security-review`는 headless에서 출력이 없어 사용 불가.
**트레이드오프**: PR당 claude 호출이 최대 4회로 비용·시간이 늘어난다. `gh api`는 POST 게시가 가능하므로 C의 허용 도구에서 제외한다.

### ADR-003: GitHub I/O는 gh CLI
**Status**: Accepted
**결정**:
- 조회: `gh api repos/{o}/{r}/pulls/{n}`(head SHA, author), `gh pr diff {n} -R {o}/{r}`, `gh api user`(현재 사용자 login).
- 테스트 결과: `gh run list -R {o}/{r} --commit {sha} --json databaseId,status,conclusion` → 완료된 최신 run에서 `gh run download {id} -R {o}/{r} -n {artifact} -D {tmpdir}`. 기본 artifact 이름 `junit-results`.
- 게시: `POST repos/{o}/{r}/pulls/{n}/reviews`(body JSON을 `--input -`로 stdin 전달: `commit_id`, `event`, `body`, `comments[{path,line,side:"RIGHT",body}]`) 1건 + `POST repos/{o}/{r}/issues/{n}/comments` 요약 1건.
**이유**: gh가 설치·인증되어 있어 토큰 관리가 필요 없다.
**트레이드오프**: gh 설치가 실행 전제가 된다. 인라인 코멘트의 line이 diff 밖이면 GitHub가 리뷰 전체를 422로 거부하므로 사전 필터가 필수다.

### ADR-004: 외부 호출은 runner 주입으로 격리
**Status**: Accepted
**결정**: `gh`/`claude`를 호출하는 함수는 `runner: Callable[[list[str], str | None], CompletedProcess]` 형태의 인자를 받는다(두 번째 인자는 stdin 입력). 기본값은 `pr_reviewer/proc.py`의 `run_process`(`subprocess.run` 래퍼, UTF-8, `shell=False`). 테스트는 fake runner로 명령 인자와 stdin을 검증하고 고정 출력을 돌려준다.
**이유**: 테스트에서 실제 GitHub 게시와 과금 호출을 막는다. 실제 호출은 phase 완료 후 수동 E2E에서만 한다.
**트레이드오프**: 실제 CLI 출력 형식 변화는 단위 테스트로 잡지 못한다.

### ADR-005: 심각도 정책
**Status**: Accepted
**결정**:
- 등급 3단계: `critical` / `major` / `minor`.
  - critical: 정상 사용 경로에서 크래시·데이터 손상·보안 침해가 확정적으로 발생.
  - major: 특정 조건(경계값, 특정 동등분할 클래스, 조건부 악용 경로)에서만 오동작.
  - minor: 현재 결함은 아니나 방어 부족, 하드닝 제안.
- 에이전트 A(실행 근거): 변경 라인에 매핑된 테스트 실패 = critical. 변경 라인 매핑 근거가 없는 실패 = 인라인 없이 요약에 major로 기록.
- 에이전트 B, C(정적 추정): critical/major는 `failure_scenario`(입력 → 기대 vs 실제)가 비어 있으면 한 단계 강등. critical은 `reachability`(정상 호출 흐름에서 도달 가능한 근거)가 비어 있으면 major로 강등. 요약에 "정적 분석 기반 추정 등급, 실행 검증 아님" 고지.
- 병합: 같은 `path+line`은 코멘트 하나로 합치고 높은 등급을 쓰며 관점 라벨(`[구조 기반 테스트]`, `[보안]`, `[코드 리뷰]`)을 붙인다.
- 게시: 전 등급 인라인. diff 밖 라인은 요약으로 강등. 강등 후 critical이 1건 이상이면 review event `REQUEST_CHANGES`, 아니면 `COMMENT`. PR 작성자 == 현재 gh 사용자이면 `COMMENT`로 대체하고 요약에 "Critical 있음(변경 요청 대상)"을 표시한다.
**이유**: 테스트를 실행하지 않은 정적 판정은 critical 오탐 위험이 있고, REQUEST_CHANGES는 머지를 막으므로 근거 없는 고등급을 코드로 억제한다. GitHub는 자기 PR에 REQUEST_CHANGES를 422로 거부한다.
**트레이드오프**: 실제 critical이 근거 기재 누락으로 major로 내려갈 수 있다.

### ADR-006: PR 루프 — 한 workflow job 체인 · self-hosted · 단계 간 계약 · workflow 내부 게이트
**Status**: Accepted (2026-10-25, 실장 위임 D-6 · 플랜 `C:\lab\2nd_NGV\docs\plans\2026-10-25-pr-autofix-loop-1차.md`)
**결정**:
- PR 루프는 workflow 하나(`pr-loop.yml`) 안의 job 체인이다: test → review → autofix-gate → fix → reverify → merge-gate → merge → release-gate → release. 모든 job은 `runs-on: [self-hosted, vsm-loop]`.
- 단계 스크립트는 `loop/`에 두고, workflow는 `working-directory: ${{ vars.LOOP_HOME }}`에서 `py -m loop.<단계> --workspace <vsm checkout>`로 부른다. `LOOP_HOME`은 runner PC의 test_harness 로컬 경로다.
- 단계 간 데이터는 `<workspace>/out/<단계>.json`(스키마 `loop/contract.py`)이다. job 사이는 artifact `loop-<단계>`로 옮긴다.
- 게이트는 되돌리기 어려운 동작(수정 push · 머지 · 릴리스) 바로 앞에 두고, workflow 안에서만 막는다(BLOCK = exit 1 → 다음 동작 job skip). Free 개인 계정 private 저장소는 branch protection · ruleset이 403이다(2026-10-25 실측).
- 토큰은 `GITHUB_TOKEN`(`permissions: contents: write, pull-requests: write`)만 쓴다. PAT로 push하면 새 run이 자동으로 돌아 Fix가 반복될 수 있다.
- test·reverify 단계는 판정하지 않는다. make 결과·분류(unexpected/fixed/missing)를 넘기고 판정은 게이트가 한다. 분류 기준 목록은 base 브랜치 판 `tests/expected_failures.txt`다(PR이 목록을 고쳐 실패를 숨기지 못하게).
- 안전 레일: Fix 상한 1회(PR 고유 커밋 `origin/<base>..HEAD`의 `Loop-Fix:` 트레일러) · 실습용 prerelease만 · job timeout 30분 + claude 900초 · 인라인은 commentable line만(ADR-003).
- workflow 구조 테스트는 PyYAML을 **테스트에서만** 쓴다(설치됨, `vsm_test/tests/test_ci_workflow.py` 선례). 구현 코드는 ADR-001대로 표준 라이브러리만.
**이유**: 실습에서 루프 전체가 Actions 화면에 job 단위로 보여야 하고, 게이트가 막는 지점이 체크 색으로 드러나야 한다. 수강생 PC가 runner이므로 claude 인증과 test_harness 로컬 경로를 그대로 쓸 수 있다.
**트레이드오프**: 사람이 수동으로 머지하는 것은 막지 못한다. 한 run 안에서 job마다 checkout·artifact 왕복 시간이 든다. LOOP_HOME이 로컬 경로라 runner PC에 test_harness가 있어야 한다.
