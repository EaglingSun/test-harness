# 프로젝트: pr-reviewer

> 공통 응답 스타일과 MVP-First Guard 원칙은 글로벌 CLAUDE.md를 따른다.
> 이 파일에는 프로젝트 고유 규칙과, 팀원도 지켜야 하는 Scope Lock만 둔다.

## 기술 스택
- Python 3.13 표준 라이브러리 + pytest. 외부 CLI: `gh`, `claude` (ADR-001~003)

## 아키텍처 규칙
- CRITICAL: 테스트에서 실제 `gh`/`claude` 프로세스를 실행하지 마라. 외부 호출은 runner 주입으로 fake 처리한다 (ADR-004). 이유: 실제 GitHub 게시와 과금 호출 방지.
- CRITICAL: step 세션에서 실제 PR에 게시하거나 `py -m pr_reviewer`를 `--dry-run` 없이 실행하지 마라. 실제 게시는 phase 완료 후 Human 확인을 받고 수동 E2E로만 한다.
- CRITICAL: 인라인 코멘트는 diff의 commentable line(RIGHT side)에만 단다. 이유: 범위 밖 line이 하나라도 있으면 GitHub가 리뷰 전체를 422로 거부한다.
- 외부 프로세스는 `shell=False` 인자 리스트로 실행한다.
- 모듈 경계는 `pr_reviewer/models.py` dataclass로만 주고받는다.

## Scope Lock (MVP-First Guard 적용)
- CRITICAL: 구현 범위는 `docs/PRD.md`의 "MVP 범위"와 현재 step 파일의 "변경 허용 범위"로 한정한다.
- CRITICAL: 리뷰와 검증은 승인된 AC만 기준으로 한다. 결함 수정은 기존 범위 안에서만 한다.
- CRITICAL: 범위 밖 아이디어는 코드로 구현하지 말고 `docs/PROPOSALS.md`에 한 줄씩 추가한다. 승인 표시(`[x]`)는 Human만 한다.
- 범위 검증: `python3 scripts/scope_check.py phases/{task}/step{N}.md`

## Phase 실행
- CRITICAL: 승인된 phase 계획의 구현은 `/run-phase` 절차(execute.py)로만 한다. "계획 실행", "구현 시작", "계획대로 구현해" 같은 요청도 메인 세션에서 직접 코드를 고치지 말고 `/run-phase`를 따른다.
- CRITICAL: execute.py 실행 중(`phases/.running` 있음)에는 메인 세션에서 코드와 문서를 수정하지 않는다. 진행 확인은 `phases/<phase>/index.json`으로 한다.

## 개발 프로세스
- 테스트를 먼저 쓰고, 테스트를 통과시키는 구현을 쓴다 (TDD).
- 커밋 메시지는 conventional commits 형식을 따른다.

## 명령어
```bash
py -m pytest -q                                   # 전체 테스트 (Stop hook VERIFY와 동일)
py -m pr_reviewer <owner/repo> <PR번호> --dry-run   # 게시 없이 payload 확인
```

## 하네스 현황
```bash
python3 scripts/harness_map.py            # harness_map.html 생성 (execute.py가 자동 갱신)
python3 scripts/harness_map.py --strict   # Health error 시 exit 1 (CI용)
```
