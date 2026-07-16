# dapa-report-harness TODO (과제 마감: 2026-07-16 23:59)

## D-2 (07-14) 스캐폴딩
- [x] 주제 확정: 방위사업 보고서 하네스 — 공통 게이트 + 파이프라인 2개 (동향보고/국회답변)
- [x] 디렉토리 골격 생성
- [x] 에이전트 프롬프트 7개 (.claude/agents/)
- [x] 오케스트레이터 커맨드 2개 (.claude/commands/)
- [x] 결정론적 게이트 gate.py (stdlib only) — 4개 시나리오 셀프테스트 통과 (07-14)
- [x] 스키마 5종 + config (도메인 화이트리스트, 민감어)
- [x] README.md 초안 (실행 예시 섹션은 실측 후 채움)

## D-1 (07-15) 실측 완주
- [x] 파이프라인 A 실행: 방사청 실제 보도자료 5건 → completed (rev1, format 지적 1건 수정 루프 실증) → examples/daily-brief-run/
- [x] 파이프라인 B 실행: 모의 질의(공개 소재) + 법령 8건 원문 실조회 → completed (rev1, citation 3건+format 1건 수정 루프 실증) → examples/assembly-reply-run/
- [x] gate.py 셀프테스트 (4개 시나리오, 07-14) + 실측 중 스키마 게이트가 감사자 계약 위반 실제 차단 (07-15)
- [x] README 실행 예시 섹션 실측 결과로 채움

## D-Day (07-16) 제출
- [x] 리뷰 라운드: codex CLI(설계·게이트) + 독립 에이전트(문서·예시, gemini 인증만료 대체) → 치명 2건(README 플레이스홀더·법령 URL 공백)+게이트 보강 5건 수용, 예시 문체 지적은 실측보존 원칙으로 기각
- [x] 게이트 보강: gaps 검사·기형 토큰·stale final 삭제·타입 검증·id 패턴 + selftest.py 10/10, 실측 4개 폴더 재판정 전부 completed
- [x] 비밀정보·개인 경로 스캔 통과
- [x] GitHub 레포 생성·푸시 완료: https://github.com/cookiesh1/dapa-report-harness (public 검증, 07-16)
- [ ] 제출 (레포 주소) — 사용자가 포털에 제출

## 불변 원칙
- 공개 자료만 사용 (보도자료·국회 공개 질의·법령). 내부 자료 절대 금지.
- 검증 실패 = human_review_required로 종료. 자동 완료 위장 금지.
- final은 gate status==completed일 때만 생성.
