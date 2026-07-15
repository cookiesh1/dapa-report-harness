# 방위사업 보고서 하네스 (DAPA Report Harness)

> 하나의 **결정론적 검증 게이트** 위에서 두 가지 방위사업 실무 보고서 —
> **일일 동향보고**와 **국회질의 답변자료** — 를 생성·검증하는 멀티에이전트 하네스.
> 근거 없는 문장이 최종 보고서에 실리는 것을 LLM의 선의가 아니라 **코드로** 차단한다.

---

## 1. 하네스 주제

방위사업 분야의 보고서 업무는 두 가지 공통 요구를 가진다.

1. **근거 정확성** — 법령 조문 하나, 수치 하나가 틀리면 사고가 되는 영역이다.
2. **보안** — 공개해서는 안 될 표현이 문서에 섞이면 안 된다.

이 요구는 보고서 종류가 달라도 동일하다. 그래서 이 하네스는 파이프라인별로
검증을 따로 만들지 않고, **공통 게이트 하나를 두 파이프라인이 공유**하는 구조로
설계했다.

| 파이프라인 | 입력 | 출력 |
|---|---|---|
| A. 일일 동향보고 | 공개 보도자료·기사 원문 (`data/inbox/`) | 공문식 일일 동향보고 |
| B. 국회질의 답변자료 | 국회 서면질의 1건 (`data/queries/`) | 공문식 쟁점별 답변자료 |

모든 입력·근거는 **공개 자료만** 사용한다 (보도자료, 국가법령정보센터, 국회 공개
질의). 내부 자료는 취급하지 않는다.

## 2. 구성 목적

1. **자기검증 편향 차단** — 작성 에이전트와 감사 에이전트를 분리하고, 최종 판정은
   에이전트가 아닌 **결정론적 Python 게이트**가 내린다. 같은 산출물에는 항상 같은
   판정이 나온다.
2. **환각의 구조적 차단** — 작성자는 수집 단계가 만든 카탈로그(`[S#]`/`[E#]`)만
   인용할 수 있고, 게이트가 모든 인용 토큰의 실존을 코드로 대조한다. "기억에 있는
   법령"은 이 하네스에서 존재하지 않는 것으로 취급된다.
3. **안전한 실패** — 근거 공백·민감어·감사 불통과는 자동 완료로 위장되지 않고
   `human_review_required`로 종료된다. 최종본(`06_final_*.md`)은 게이트가
   `completed`를 판정했을 때만 생성된다.
4. **하네스 재사용성 증명** — 동일한 게이트·작성자·감사자 위에 입력이 전혀 다른
   두 업무를 올려, 검증 구조가 특정 업무에 종속되지 않음을 보인다.

## 3. 전체 구조

**입력**(`data/` 공개 자료) → **처리**(수집·분석 에이전트 → 작성 에이전트) →
**검증**(독립 감사 2종 병렬 + 결정론적 게이트) → **출력**(`06_final_*.md`,
게이트 통과 시에만 생성)의 흐름이며, 아래 다이어그램의 세로축이 그 순서다.

```text
        파이프라인 A (동향보고)              파이프라인 B (국회답변)
        data/inbox/*.md                     data/queries/q.md
              │                                   │
              ▼                                   ▼
      source-collector                      issue-analyst
      01_sources.json ◄─카탈로그            01_issues.json
              │                                   │  (민감 쟁점 → 사용자 확인)
              ▼                                   ▼
       trend-analyst                      evidence-searcher
      02_analysis.json                    02_evidence.json ◄─카탈로그
              │                                   │  (법령·공식자료 실조회, gaps 정직 기록)
              └────────────┬──────────────────────┘
                           ▼
                  ┌─ 공 통 구 간 ─────────────────────────────┐
                  │        report-writer                      │
                  │  03_draft.md — 카탈로그 토큰만 인용        │
                  │             │                             │
                  │      ┌──────┴──────┐   ★ 병렬            │
                  │      ▼             ▼                      │
                  │ citation-auditor  format-auditor          │
                  │ 주장-근거 대응     공문 양식·문체·민감표현  │
                  │ 04_citation_...   04_format_...           │
                  │      └──────┬──────┘                      │
                  │             ▼                             │
                  │   ▣ gate.py (결정론적, LLM 아님)          │
                  │   ① 스키마  ② 인용 토큰 실존              │
                  │   ③ 도메인 화이트리스트  ④ 민감어 스캔     │
                  │   ⑤ 감사 verdict 종합                     │
                  └──────────────┬────────────────────────────┘
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
         completed        revision_required   human_review_required
       06_final_*.md      writer 재작성 1회         / failed
        (이때만 생성)      → 재감사 → 재게이트      final 없음, 사유 보고
```

### 에이전트 역할표 (7개 + 오케스트레이터)

| 단계 | 에이전트 | 책임 | 하지 않는 일 | 산출물 |
|---|---|---|---|---|
| A-수집 | `source-collector` | 보도자료 원문 → 출처 카탈로그 | 요약·해석·추측 | `01_sources.json` |
| A-분석 | `trend-analyst` | 카탈로그 근거로 분류·중요도·시사점 | 카탈로그 밖 지식 사용 | `02_analysis.json` |
| B-분석 | `issue-analyst` | 질의를 쟁점으로 분해, 민감도 판정 | 답변 구상 | `01_issues.json` |
| B-근거 | `evidence-searcher` | 법령·공식자료 실조회, 공백 정직 기록 | 미확인 조문 생성 | `02_evidence.json` |
| 공통-작성 | `report-writer` | 카탈로그만 인용해 공문식 초안 | 새 사실·새 토큰 창작 | `03_draft.md` |
| 공통-감사 | `citation-auditor` | 주장-인용-근거 대응 독립 감사 | 초안 수정 | `04_citation_audit.json` |
| 공통-감사 | `format-auditor` | 공문 양식·문체·민감표현 감사 | 인용 정확성 판정 | `04_format_audit.json` |
| 판정 | **`gate.py`** (코드) | 5개 검사 종합, 상태 확정, final 생성 | — | `05_gate_decision.json`, `06_final_*.md` |
| 조율 | 오케스트레이터 (커맨드) | 위임·전달·게이트 실행·보고 | 내용 작성, 판정 번복 | `00_input.md` |

### 결정론적 게이트 (`harness/gates/gate.py`)

LLM 감사만으로는 "그럴듯한 통과"를 막을 수 없다. 게이트는 표준 라이브러리만 쓰는
Python 코드로 다음을 검사하며, **모델을 호출하지 않는다**:

| # | 검사 | 실패 시 |
|---|---|---|
| 1 | 산출물 존재·JSON·간이 스키마 — 필수 키, 배열 타입, id 형식·중복 (`harness/schema/`) | `failed` |
| 2 | 초안의 모든 `[S#]`/`[E#]` 토큰이 카탈로그에 실존 (기형 토큰 `[S1a]` 등도 검출) | `revision_required` |
| 3 | 출처 URL이 공식 도메인 화이트리스트 안 (`config/domains.json`). B라인은 URL 필수, A라인의 URL 없는 출처는 '검증 불가' 경고로 기록 | `revision_required` |
| 4 | 민감어 미포함 (`config/sensitive_terms.json`) | `human_review_required` (재작성 우회 불가) |
| 5 | 근거 공백(B라인) — 근거 0건이면 사람 검토, 부분 공백(`gaps`)이면 초안에 "확인 불가" 명시 강제 | `human_review_required` / `revision_required` |
| 6 | 두 감사 verdict — ESCALATE 있으면 사람 검토, REVISE면 재작성 | 좌동 |

재작성은 실행당 **1회**로 제한하고, 그래도 통과 못 하면 `MAX_REVISIONS_REACHED`로
사람 검토에 넘긴다. 판정이 `completed`가 아니면 이전 실행이 남긴 `06_final_*.md`도
삭제한다 (stale final 방지).

**게이트가 보증하는 것과 하지 않는 것** — 게이트가 코드로 보증하는 범위는
①인용 토큰의 카탈로그 실존 ②출처 도메인 ③민감어 ④산출물 계약이다. 카탈로그
내용 자체의 충실성(발췌가 원문과 일치하는지, 주장이 근거 범위를 벗어나지
않는지)은 독립 감사 에이전트(citation-auditor)의 원문 대조에 의존하며, 이
경계를 명확히 하는 것이 이 하네스의 설계 원칙이다.

### 상태 정의

| 상태 | 의미 | `06_final_*.md` |
|---|---|---|
| `completed` | 5개 검사 전부 통과 | **이때만 생성** |
| `revision_required` | 수정 가능한 위반 (revision 0에서만) | 없음 |
| `human_review_required` | 민감어·ESCALATE·재작성 한도 초과·근거 공백 | 없음 |
| `failed` | 산출물 누락·스키마 위반 — 해당 산출물을 다시 만들면 게이트 재실행으로 재개 가능 | 없음 |

## 4. 사용 방법

요구 환경: [Claude Code](https://claude.com/claude-code) + Python 3.10+ (게이트는 표준 라이브러리만 사용).

```bash
git clone https://github.com/cookiesh1/dapa-report-harness.git
cd dapa-report-harness
claude
```

### 파이프라인 A — 일일 동향보고

공개 보도자료 원문을 `data/inbox/`에 `.md`로 넣고:

```
/daily-brief
```

### 파이프라인 B — 국회질의 답변자료

공개 서면질의를 `data/queries/q1.md`로 넣고:

```
/assembly-reply data/queries/q1.md
```

### 게이트 단독 실행 (재현·감사용)

에이전트 없이도 기존 실행 폴더에 게이트만 다시 걸 수 있다. 결정론적이므로 언제
실행해도 같은 판정이 나온다. `examples/`의 실측 산출물로 직접 확인할 수 있다:

```bash
python3 harness/gates/gate.py --run-dir examples/daily-brief-run --pipeline daily --revision 1
python3 harness/gates/gate.py --run-dir examples/assembly-reply-run --pipeline reply --revision 1
```

### 게이트 셀프테스트

10개 시나리오(정상 통과, 깨진 인용, 재작성 한도, 기형 토큰, 민감어, 비허용
도메인, 근거 0건, gaps 명시 강제, 타입 위반, stale final 삭제)를 검증한다:

```bash
python3 harness/gates/selftest.py
```

## 5. 실행 예시 (실측)

`examples/`에 두 파이프라인의 **실제 실행** 산출물 전체(00_input → 06_final)가
들어 있다. 두 실행 모두 2026-07-15에 수행했고, 각각 실제 수정 루프를 한 차례
거쳐 통과했다.

### 파이프라인 A — [examples/daily-brief-run/](examples/daily-brief-run/)

- **입력**: 방위사업청 실제 보도자료 5건 (방산혁신클러스터 협약, 방위산업의 날,
  무인기용 항공엔진 공개, 캐나다 잠수함사업 입장, 드론 국방표준서 제정)
- **검증에서 실제로 걸린 것**:
  1. format-auditor 산출물이 스키마의 필수 키를 누락 → 게이트가 `failed`로 차단
     (감사자조차 계약을 어기면 통과 못 함) → 계약 준수 재출력 후 재개
  2. format-auditor가 STRUCTURE 위반 1건('한 항목 한 내용' 위반) 검출 →
     `revision_required` → writer 1회 재작성 → 재감사 PASS
- **최종**: revision 1에서 `completed`, [06_final_report.md](examples/daily-brief-run/06_final_report.md)
  생성 (출처 5건 전부 인용, 시사점의 추론 문장은 전부 `(추론)` 표기)

### 파이프라인 B — [examples/assembly-reply-run/](examples/assembly-reply-run/)

- **입력**: 모의 서면질의 1건 (소재는 전부 공개 사안 — 방위사업추진위원회 근거,
  방산 중소·벤처 지원 법령, 캐나다 잠수함사업 입장)
- **근거 검색**: 법령 8건은 법제처 국가법령정보센터에서 **조문 원문을 실조회**해
  발췌 기록, 보도자료 2건은 dapa.go.kr 원문. 확인 못 한 세부자료 2건은 `gaps`로
  정직하게 기록 → 초안의 "확인 불가 사항" 섹션에 반영
- **검증에서 실제로 걸린 것** (citation-auditor 3건 + format-auditor 1건):
  1. 위원회 심의·조정 사항을 "14개 호"로 서술 — 원문은 제11호의2 포함 15개 항목
  2. 법문에 없는 "민간 전문가" 표현 (법 제9조제4항의 실제 문언과 불일치)
  3. 장성급 장교 포함 위원 구성을 "실·국장급"으로 일괄 서술
  4. 과장어 "비약적" → 보도자료 원문 직접인용으로 전환
  → `revision_required` → writer 1회 재작성 → 재감사 양측 PASS → `completed`
- **덤으로 잡힌 것**: 질의가 위원회 "심의·의결" 사항을 물었으나 법문상 권한은
  "심의·조정" — 근거 검색 단계에서 법문 대조로 발견해 답변 서두에 명시

두 실행 모두 게이트 판정 이력이 `05_gate_decision.json`에, 감사 지적 전문이
`04_*.json`에 그대로 남아 있어 재구성·감사가 가능하다.

**제출 전 보완 이력 (투명성 기록)**: 실측 후 외부 리뷰(codex CLI + 독립 에이전트)
라운드에서 ①법령 URL의 공백 미인코딩(GitHub에서 링크가 끊겨 다른 조문이 열리는
문제)을 발견해 근거 카탈로그·초안·최종본의 URL을 `%20` 인코딩으로 일괄 수정했고
②게이트에 근거 공백(gaps) 검사·기형 토큰 검출·stale final 삭제를 보강한 뒤
게이트를 재실행해 두 실행 모두 `completed` 판정을 재확인했다. "총 15개 항목"
등 법령 수치는 제출 전 법제처 원문과 재대조를 마쳤다.

## 6. 안전 원칙

1. 모든 결과물은 **담당자 검토 전 초안**이다. 최종본에도 검토 필요 문구가 박힌다.
2. 공개 자료만 입력으로 사용한다. 내부 문서·비공개 정보는 취급하지 않는다.
3. 근거 공백은 공백대로 보고한다 — "확인 불가"가 그럴듯한 답변보다 낫다.
4. 게이트 판정은 오케스트레이터·에이전트 누구도 번복할 수 없다.

## 7. 저장소 구조

```text
.claude/
  agents/          # 에이전트 7개 시스템 프롬프트
  commands/        # /daily-brief, /assembly-reply 오케스트레이터 SOP
harness/
  gates/gate.py    # 결정론적 품질 게이트 (stdlib only)
  gates/selftest.py# 게이트 셀프테스트 10개 시나리오
  schema/          # 산출물 간이 스키마 5종 (필수 키·id 패턴)
  config/          # 도메인 화이트리스트, 민감어 목록
data/
  inbox/           # 파이프라인 A 입력 (공개 보도자료 원문)
  queries/         # 파이프라인 B 입력 (공개 서면질의)
examples/          # 실측 실행 산출물
outputs/           # 실행별 산출물 (run_id 격리, git 미포함)
```
