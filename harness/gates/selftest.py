#!/usr/bin/env python3
"""gate.py 셀프테스트 — 픽스처를 임시 폴더에 만들고 8개 시나리오의 판정을 검증한다.

사용법: python3 harness/gates/selftest.py
표준 라이브러리만 사용. 모든 시나리오 통과 시 exit 0.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

GATE = Path(__file__).resolve().parent / "gate.py"

SOURCES = {
    "run_id": "t", "collected_at": "2026-07-15",
    "sources": [{"id": "S1", "title": "방위사업청 보도자료", "publisher": "방위사업청",
                 "date": "2026-07-10", "url": "https://www.dapa.go.kr/dapa/x.do",
                 "excerpt": "테스트 발췌문."}],
    "warnings": [],
}
ANALYSIS = {
    "run_id": "t",
    "items": [{"source_ids": ["S1"], "category": ["방산수출"], "headline": "테스트",
               "importance": "상", "importance_reason": "테스트", "implication": "테스트"}],
    "daily_summary": {"text": "테스트", "source_ids": ["S1"]},
}
ISSUES = {
    "run_id": "t", "query_file": "q.md",
    "issues": [{"id": "Q1", "question": "테스트?", "what_is_asked": ["사실확인"],
                "answer_scope": "테스트", "sensitivity": "일반", "needed_evidence": ["법령"]}],
}
EVIDENCE = {
    "run_id": "t",
    "evidence": [{"id": "E1", "issue_ids": ["Q1"], "type": "법령", "title": "방위사업법 제9조",
                  "url": "https://www.law.go.kr/법령/방위사업법/제9조",
                  "checked_date": "2026-07-15", "quote": "테스트 조문."}],
    "gaps": [],
}
DRAFT_S = "# 보고\n## 1. 요지\n1. 테스트임 [S1]\n## 인용 출처\n- S1\n"
DRAFT_E = "# 답변\n## 1. 답변 요지\n1. 테스트임 [E1]\n## 인용 출처\n- E1\n"
AUDIT_PASS = {"run_id": "t", "revision": 0, "verdict": "PASS", "findings": [],
              "stats": {"claims_checked": 1, "violations": 0}}


def make_run(tmp, name, pipeline, mutate=None):
    d = Path(tmp) / name
    d.mkdir()
    files = ({"01_sources.json": SOURCES, "02_analysis.json": ANALYSIS}
             if pipeline == "daily" else
             {"01_issues.json": ISSUES, "02_evidence.json": EVIDENCE})
    files["04_citation_audit.json"] = AUDIT_PASS
    files["04_format_audit.json"] = AUDIT_PASS
    data = {k: json.loads(json.dumps(v)) for k, v in files.items()}
    draft = DRAFT_S if pipeline == "daily" else DRAFT_E
    if mutate:
        draft = mutate(data, draft) or draft
    for fname, content in data.items():
        (d / fname).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    (d / "03_draft.md").write_text(draft, encoding="utf-8")
    return d


def run_gate(run_dir, pipeline, revision=0):
    r = subprocess.run([sys.executable, str(GATE), "--run-dir", str(run_dir),
                        "--pipeline", pipeline, "--revision", str(revision)],
                       capture_output=True, text=True)
    return json.loads(r.stdout)


def main():
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        # 1. 정상 → completed + final 생성
        d = make_run(tmp, "ok", "daily")
        s = run_gate(d, "daily")
        results.append(("정상 통과", s["status"] == "completed"
                        and (d / "06_final_report.md").exists()))

        # 2. 카탈로그에 없는 토큰 → revision_required
        d = make_run(tmp, "broken", "daily",
                     lambda a, dr: dr + "\n2. 없는 근거 [S9]\n")
        results.append(("깨진 인용", run_gate(d, "daily")["status"] == "revision_required"))

        # 3. revision 1에서 같은 위반 → human_review (MAX_REVISIONS)
        results.append(("재작성 한도", run_gate(d, "daily", 1)["status"] == "human_review_required"))

        # 4. 기형 토큰 → revision_required
        d = make_run(tmp, "malformed", "daily",
                     lambda a, dr: dr + "\n2. 기형 [S1a]\n")
        results.append(("기형 토큰", run_gate(d, "daily")["status"] == "revision_required"))

        # 5. 민감어 → human_review_required
        d = make_run(tmp, "sensitive", "daily",
                     lambda a, dr: dr + "\n2. 작전계획 연계 [S1]\n")
        results.append(("민감어", run_gate(d, "daily")["status"] == "human_review_required"))

        # 6. 비허용 도메인 → revision_required
        def bad_domain(a, dr):
            a["02_evidence.json"]["evidence"][0]["url"] = "https://blog.example.com/x"
        d = make_run(tmp, "domain", "reply", bad_domain)
        results.append(("비허용 도메인", run_gate(d, "reply")["status"] == "revision_required"))

        # 7. 근거 0건 → human_review_required (INSUFFICIENT_EVIDENCE)
        def no_evidence(a, dr):
            a["02_evidence.json"]["evidence"] = []
            return "# 답변\n## 1. 답변 요지\n1. 테스트임 [E1]\n"
        d = make_run(tmp, "noev", "reply", no_evidence)
        results.append(("근거 0건", run_gate(d, "reply")["status"] == "human_review_required"))

        # 8. gaps 있는데 '확인 불가' 미명시 → revision_required, 명시하면 completed
        def with_gaps(a, dr):
            a["02_evidence.json"]["gaps"] = [{"issue_id": "Q1", "reason": "자료 없음"}]
        d = make_run(tmp, "gaps", "reply", with_gaps)
        first = run_gate(d, "reply")["status"] == "revision_required"
        (d / "03_draft.md").write_text(DRAFT_E + "\n## 3. 참고사항\n- 확인 불가: 테스트\n",
                                       encoding="utf-8")
        second = run_gate(d, "reply", 1)["status"] == "completed"
        results.append(("gaps 명시 강제", first and second))

        # 9. 스키마 타입 위반(sources가 문자열) → failed, 크래시 없음
        def bad_type(a, dr):
            a["01_sources.json"]["sources"] = "문자열"
        d = make_run(tmp, "badtype", "daily", bad_type)
        results.append(("타입 위반", run_gate(d, "daily")["status"] == "failed"))

        # 10. 판정 번복 시 stale final 삭제
        d = make_run(tmp, "stale", "daily")
        run_gate(d, "daily")  # completed → final 생성
        (d / "03_draft.md").write_text(DRAFT_S + "\n2. 없는 근거 [S9]\n", encoding="utf-8")
        run_gate(d, "daily")  # revision_required로 뒤집힘
        results.append(("stale final 삭제", not (d / "06_final_report.md").exists()))

    ok = all(passed for _, passed in results)
    for name, passed in results:
        print(("✅" if passed else "❌"), name)
    print(f"\n{sum(p for _, p in results)}/{len(results)} 통과")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
