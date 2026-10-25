# Proposals (범위 밖 제안 백로그)

> 규칙
> - Claude는 `[ ]` 항목만 추가한다. 기존 항목의 수정, 삭제, 승인 표시는 하지 않는다.
> - Human이 `[x]`로 승인하면, 다음 phase 설계(/harness C단계)에서 PRD의 MVP 범위로 옮긴 뒤 구현한다.
> - 형식: `- [ ] P{번호} | {출처 phase/step} | {제안 한 줄} | {이유}`

- [ ] P1 | example/step0 | {예: 실패 시 스크린샷 자동 첨부} | {예: 디버깅 시간 단축}
- [ ] P2 | 0-mvp/design | 유지보수성 관점 리뷰 에이전트 추가 | 관점 1개 원칙으로 MVP에서 제외됨
- [ ] P3 | 0-mvp/design | Critical 지적마다 재현 테스트를 생성·실행해 등급 확정 | 정적 추정 등급의 오탐 감소
- [ ] P4 | 0-mvp/design | GitHub Actions pull_request 이벤트 자동 트리거 | 수동 CLI 실행 제거
- [ ] P5 | 0-mvp/design | 커버리지 리포트(Cobertura 등) 연계로 미커버 변경 라인 지적 | 구조 기반 테스트 관점 강화
- [ ] P6 | 0-mvp/design | 재리뷰 시 기존 봇 코멘트 갱신/정리 | 중복 코멘트 방지
- [ ] P7 | 0-mvp/design | 대형 diff 분할 리뷰, 모델 선택 옵션 | 큰 PR 대응과 비용 조절
- [ ] P8 | 0-mvp/step6 | JUnit run 조회(`gh run list`)·요약 코멘트 게시의 GhError도 CLI에서 잡아 stderr 메시지+exit 1로 처리 | 현재는 traceback으로 종료
- [ ] P9 | 0-mvp/review | git이 따옴표로 감싼 비ASCII 파일 경로(`+++ "b/\355..."`)를 diff.py에서 해석해 인라인 대상에 포함 | 현재는 해당 파일 지적이 모두 요약 전용으로 강등됨
- [ ] P10 | 0-mvp/E2E | 스모크 절차 문서화(`docs/SMOKE.md`)와 S1~S5 기대 결과 자동 대조 스크립트 | 실습에서 리뷰어 수정 후 반복 검증
- [ ] P11 | 0-mvp/E2E | 구조 기반 테스트: 실패를 base 브랜치 최신 run 결과와 비교해 "기존 실패/신규 실패"를 결정적으로 구분 | 현재는 LLM이 원인 위치로 판단, base에서도 실패하면 이 PR 무관이 확정됨
- [ ] P12 | 1-loop-nogate/step0 | scope_check.py가 `/`로 끝나는 허용 패턴(`tests/fixtures/loop/`)을 디렉터리 접두사로 해석 | 현재 fnmatch 완전 일치라 하위 파일이 모두 위반으로 잡혀 step0.md를 `tests/fixtures/loop/*`로 고쳤다(step3.md도 같은 패턴)
- [ ] P13 | 6-loop-degraded/design | review 계약 counts를 게시 요약과 같은 집계 후 등급으로 맞추거나 두 값을 함께 기록 | 1차 D5: 원천 등급 critical 0 ≠ 게시 요약 Critical 1 (현재 counts_basis: agent_raw 표시만)
