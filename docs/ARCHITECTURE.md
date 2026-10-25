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
tests/
├── test_diff.py
├── test_github.py
├── test_junit.py
├── test_runner.py
├── test_agents.py
├── test_aggregate.py
└── test_cli.py
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

## 상태 관리
상태 없음. 한 번 실행에 PR 한 건을 처리하고 종료한다. 임시 파일(artifact 다운로드)은 `tempfile.TemporaryDirectory`로 만들고 실행 후 삭제한다.
