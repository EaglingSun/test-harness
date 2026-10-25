# 아키텍처

## 디렉토리 구조
```
pyproject.toml          # pytest 설정 (pythonpath = ["."])
pr_reviewer/
├── __init__.py
├── __main__.py         # CLI 진입점 + 파이프라인 조립 (R6)
├── models.py           # dataclass: Finding, TestFailure, PullRequest, AgentResult 등
├── proc.py             # Runner 타입 + 기본 subprocess 래퍼 run_process (ADR-004)
├── diff.py             # unified diff 파싱 → 파일별 commentable line 집합 (R1)
├── github.py           # gh CLI 래퍼: PR/diff/사용자 조회, artifact 다운로드, 리뷰·코멘트 게시 (R1, R2, R5)
├── junit.py            # JUnit XML → TestFailure 목록 (R2)
├── runner.py           # claude -p 호출, JSON 결과 파싱, 병렬 실행 + 부분 실패 처리 (R3)
├── agents.py           # 에이전트 A/B/C 정의: 프롬프트, findings schema, category 필터 (R3)
└── aggregate.py        # 심각도 규칙, 병합, 강등, review event 결정, markdown 요약 (R4, R5)
loop/                   # PR 루프 단계 스크립트 (R7, R8, R10) — workflow가 `py -m loop.<단계>`로 부른다
├── __init__.py
├── contract.py         # 단계 간 계약 JSON(out/<단계>.json) 스키마 · 읽기/쓰기/검증
├── test_report.py      # test · reverify 단계: JUnit XML + base 기준 목록 → 분류(unexpected/fixed/missing)
├── review.py           # review 단계: stub(고정 findings) / real(pr_reviewer 실행)
├── gate.py             # autofix · merge · release 게이트 (1차 무게이트: 항상 통과)
├── fix.py              # fix 단계: stub(고유 파일 커밋 + Loop-Fix 트레일러)
├── finish.py           # merge · release 단계 (gh, 멱등)
├── run_local.py        # fake runner로 전 단계를 로컬에서 한 바퀴
└── templates/
    └── pr-loop.yml     # 강사 키트 workflow 틀 (vsm 저장소 .github/workflows/ 에 복사)
tests/
├── test_diff.py
├── test_github.py
├── test_junit.py
├── test_runner.py
├── test_agents.py
├── test_aggregate.py
├── test_cli.py
├── test_proc.py        # run_process 인자 전달(cwd 등)
├── test_loop_*.py      # loop/ 단계별 테스트 · test_loop_workflow.py(yaml 구조)
└── fixtures/loop/      # run_local · 단계 테스트용 JUnit XML · 이벤트 · 기준 목록
scripts/                # 하네스 스크립트 (수정하지 않음)
```

## 패턴
- 외부 프로세스(`gh`, `claude`)는 모듈마다 `runner` 인자(기본값 `subprocess.run` 기반 함수)로 주입한다. 테스트는 fake runner를 넘긴다 (ADR-004).
- 모듈 간 데이터는 `models.py`의 dataclass로만 주고받는다. dict를 모듈 경계 밖으로 흘리지 않는다.
- 순수 로직(diff, junit, aggregate)은 I/O가 없다. I/O는 github.py, runner.py에만 있다.

## 데이터 흐름
```
CLI(owner/repo, PR)
 → github: PR 메타(head SHA, author) + diff + 현재 gh 사용자
 → diff: commentable lines
 → github: head SHA run의 JUnit artifact 다운로드 → junit: 실패 테스트 목록 (없으면 빈 목록)
 → runner: 병렬 실행 ┬ A 구조 기반 테스트 (실패 0건이면 skip)
                     ├ B 보안
                     └ C /code-review (텍스트) → JSON 변환
 → aggregate: 심각도 규칙 → 병합 → diff 밖 강등 → review event 결정 → 요약 markdown
 → github: PR Review(인라인) 1건 + Issue comment(요약) 1건   (--dry-run이면 출력만)
```

## PR 루프 데이터 흐름 (R7, R8, R10)
```
PR 이벤트 → pr-loop.yml (self-hosted, 한 workflow 안 job 체인)
 test → review → autofix-gate → fix → reverify → merge-gate → merge → release-gate → release
 각 job: working-directory = LOOP_HOME(test_harness), `py -m loop.<단계> --workspace <vsm checkout> ...`
 각 단계: out/<단계>.json 작성 → artifact loop-<단계> → 다음 job이 out/에 내려받음
```
- 게이트는 workflow 안에서만 막는다(다음 동작 job을 실행하지 않음 + 빨간 체크). Free private 저장소는 branch protection 불가(ADR-006).
- test·reverify는 판정하지 않는다. make 결과와 분류만 넘기고, 판정은 게이트가 한다.
- loop/ 의 외부 호출(gh, git, make, py -m pr_reviewer)도 ADR-004 runner 주입을 따른다.

## 상태 관리
상태 없음. 한 번 실행에 PR 한 건을 처리하고 종료한다. 임시 파일(artifact 다운로드)은 `tempfile.TemporaryDirectory`로 만들고 실행 후 삭제한다.
