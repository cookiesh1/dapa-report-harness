---
description: 파이프라인 A — 공개 보도자료로 방위사업 일일 동향보고를 생성·검증한다
---

# /daily-brief [입력 폴더 (기본 data/inbox/)]

당신은 이 실행의 **오케스트레이터**다. 내용을 직접 쓰거나 판정하지 않는다 —
단계를 순서대로 위임하고, 산출물 전달과 게이트 실행만 담당한다.

## 절차

1. **실행 준비**
   - `run_id` 생성: `daily-YYYYMMDD-HHMM` 형식. `outputs/<run_id>/` 폴더 생성.
   - `outputs/<run_id>/00_input.md`에 기록: 입력 폴더 경로, 입력 파일 목록, 실행 일시.
   - 입력 폴더에 파일이 없으면 즉시 중단하고 사용자에게 보고.

2. **수집** — `source-collector` 서브에이전트 호출.
   전달: 입력 폴더 경로, run_id, 저장 경로 `outputs/<run_id>/01_sources.json`.

3. **분석** — `trend-analyst` 서브에이전트 호출.
   전달: `01_sources.json` 경로, 저장 경로 `outputs/<run_id>/02_analysis.json`.

4. **작성** — `report-writer` 서브에이전트 호출.
   전달: 파이프라인 A임을 명시, `01_sources.json`·`02_analysis.json` 경로,
   저장 경로 `outputs/<run_id>/03_draft.md`.

5. **병렬 감사** — `citation-auditor`와 `format-auditor`를 **한 메시지에서 동시에**
   호출한다 (서로의 결과를 기다리지 않는다).
   전달: 초안·카탈로그 경로, revision 번호, 각각
   `04_citation_audit.json` / `04_format_audit.json`으로 저장.

6. **게이트** — Bash로 실행:
   ```bash
   python3 harness/gates/gate.py --run-dir outputs/<run_id> --pipeline daily --revision 0
   ```

7. **분기** — `05_gate_decision.json`의 `status`에 따라:
   - `completed` → 8로.
   - `revision_required` → `report-writer`에 두 감사 리포트와 게이트 reasons를
     전달해 **1회만** 재작성 → 5(병렬 감사)부터 재실행하되 revision=1로 →
     게이트도 `--revision 1`로 재실행. 그 결과가 무엇이든 8로.
   - `human_review_required` / `failed` → 재시도하지 않고 8로.

8. **보고** — 사용자에게 보고한다:
   - 최종 status와 reasons
   - `completed`면 `06_final_report.md` 경로와 요지 3줄
   - 그 외 상태면 사람이 확인해야 할 사항 목록 (완료된 것처럼 꾸미지 않는다)
   - 단계별 산출물 목록

## 불변 규칙
- 게이트 판정을 오케스트레이터가 뒤집지 않는다. status는 gate.py만 정한다.
- 재작성은 전체 실행에서 1회로 제한한다.
- `06_final_report.md`를 직접 만들지 않는다 (게이트만 생성 가능).
