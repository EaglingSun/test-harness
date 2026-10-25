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
