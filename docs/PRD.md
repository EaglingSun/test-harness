# PRD: pr-reviewer

## 목표
GitHub PR 한 건에 대해 관점이 다른 리뷰 에이전트 3개를 병렬로 돌리고, 결과를 취합해 인라인 코멘트와 PR 요약 코멘트로 게시한다. MVP는 "변경 코드에 대한 최초 리뷰가 실제로 게시되는지"를 빠르게 확인하는 것이 목적이다.

## 사용자
개발 저장소(예: `EaglingSun/vsm_test`)의 PR 작성자와 리뷰어. MVP에서는 개발자가 로컬에서 CLI로 수동 실행한다.

## 리뷰 에이전트 (한 에이전트 = 한 관점)
| 에이전트 | category | 입력 | 심각도 성격 |
|---------|----------|------|-----------|
| A 구조 기반 테스트 | `structural_test` | diff + 개발 저장소 CI의 JUnit XML 실패 테스트 (로직 오류, 예외 처리 누락, 경계값, 동등분할 테스트 결과) | 실행 근거 |
| B 보안 | `security` | diff | 정적 추정 |
| C 코드 리뷰 | `code_review` | PR URL (`/code-review` 스킬, 보안 지적 제외) | 정적 추정 |

## MVP 범위 (승인됨)
| ID | 요구사항 | 완료 기준 (실행 가능한 명령) |
|----|---------|---------------------------|
| R1 | PR 메타(head SHA, 작성자)와 unified diff를 조회하고, diff를 파싱해 인라인 코멘트 가능 라인(RIGHT side) 집합을 계산한다 | `pytest -q tests/test_diff.py tests/test_github.py` |
| R2 | PR head SHA의 workflow run에서 JUnit XML artifact를 받아 실패 테스트 목록으로 파싱한다. run/artifact가 없으면 에러 없이 "결과 없음"으로 처리한다 | `pytest -q tests/test_junit.py tests/test_github.py` |
| R3 | 에이전트 A/B/C를 병렬 실행해 구조화된 findings를 받는다. 하나가 실패해도 나머지로 진행하고, 에이전트 category와 다른 finding은 버린다. A는 실패 테스트가 0건이면 호출하지 않는다 | `pytest -q tests/test_runner.py tests/test_agents.py` |
| R4 | 심각도(Critical/Major/Minor) 규칙 적용(ADR-005), 같은 path+line 병합, diff 밖 라인 요약 강등, 관점별 markdown 요약 렌더링 | `pytest -q tests/test_aggregate.py` |
| R5 | 인라인 코멘트를 담은 PR Review 1건(Critical 있으면 REQUEST_CHANGES, 자기 PR이면 COMMENT)과 요약 Issue comment 1건을 게시한다 | `pytest -q tests/test_github.py tests/test_aggregate.py` |
| R6 | CLI `py -m pr_reviewer <owner/repo> <PR번호> [--dry-run] [--junit-artifact NAME]`. `--dry-run`은 게시 없이 payload를 출력한다 | `pytest -q tests/test_cli.py` |
| R7 | PR 루프 뼈대(무게이트): `loop/` 단계 스크립트(test · review · gate · fix · finish)가 단계 간 계약 JSON(`out/<단계>.json`)을 주고받고, 게이트는 항상 통과한다. `loop/run_local.py`가 fake runner로 전 단계를 한 바퀴 돈다 | `pytest -q tests/test_loop_*.py` + `py -m loop.run_local --fixture tests/fixtures/loop/basic --out <tmp>` |
| R8 | workflow 틀 `loop/templates/pr-loop.yml`: 한 workflow 안 job 체인(test → review → autofix-gate → fix → reverify → merge-gate → merge → release-gate → release), self-hosted, 고정 SHA | `pytest -q tests/test_loop_workflow.py` |
| R9 | `pr_reviewer` CLI 옵션 `--junit-dir PATH`(로컬 JUnit) · `--plan-out PATH`(payload JSON 저장) · `--current-user LOGIN`(`gh api user` 생략) | `pytest -q tests/test_cli.py` |
| R10 | 루프 review 단계 real 모드: `pr_reviewer`를 R9 옵션으로 실행하고 결과를 review 계약 JSON으로 변환 | `pytest -q tests/test_loop_review.py` |
| R11 | 게이트 강제 스위치(멈추는 장치): 실행 시점 PR 라벨 `force-block-<게이트>`가 있으면 그 게이트가 BLOCK. 라벨 조회 실패는 fail-closed. workflow는 `labeled`(force-block-* 만)로 다시 돈다 | `pytest -q tests/test_loop_gate_switch.py tests/test_loop_workflow.py` |

## MVP 제외 사항
- GitHub Actions/Webhook 자동 트리거 — 필요하면 PROPOSALS.md로 (2026-10-25: self-hosted PR 루프 R7~R10으로 일부 편입)
- 재리뷰 시 기존 코멘트 갱신/삭제
- 대형 diff 분할, 모델 선택 옵션
- 커버리지 리포트 연계, Critical 재현 테스트 자동 생성
- 개발 저장소의 JUnit artifact 업로드 workflow 작성 (개발 저장소 쪽 책임)

## 변경 이력
- 2026-10-25: 초안 승인
- 2026-10-25: R7~R10 추가(PR Autofix CI/CD 실습 1차 실측 — `C:\lab\2nd_NGV\docs\plans\2026-10-25-pr-autofix-loop-1차.md`). 실장 대화 승인(위임 D-6 · 「승인」). PROPOSALS P4 범위의 편입이며, P4의 `[x]` 표시는 Human만 하므로 건드리지 않았다.
