#!/usr/bin/env python3
"""결정론적 품질 게이트.

LLM이 아닌 코드가 최종 상태를 판정한다. 같은 산출물에는 항상 같은 결정을 내린다.

검사 항목:
  1. 산출물 존재·JSON 유효성·간이 스키마 (harness/schema/*.json)
  2. 인용 무결성 — 초안의 [S#]/[E#] 토큰이 카탈로그에 실존하는지 (기형 토큰 포함)
  3. 출처 도메인 화이트리스트 (harness/config/domains.json)
  4. 민감어 스캔 (harness/config/sensitive_terms.json)
  5. 근거 공백(gaps) 처리 — 파이프라인 B: 근거 전무면 사람 검토,
     부분 공백이면 초안에 '확인 불가' 명시 강제
  6. 두 감사(citation/format)의 verdict 종합

상태: completed | revision_required | human_review_required | failed
`06_final_*.md`는 completed일 때만 존재한다 (그 외 판정 시 이전 final도 삭제).
표준 라이브러리만 사용한다.

사용법:
  python3 harness/gates/gate.py --run-dir outputs/<run_id> --pipeline daily|reply [--revision N]
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent  # harness/
TOKEN_RE = re.compile(r"\[([SE]\d+)\]")
# 인용처럼 보이는 모든 대괄호 토큰 (기형 토큰 검출용)
TOKEN_LIKE_RE = re.compile(r"\[([SE][^\]\s]{0,9})\]")
ID_RE = re.compile(r"^[SE]\d+$")

PIPELINES = {
    "daily": {
        "artifacts": {
            "01_sources.json": "sources.schema.json",
            "02_analysis.json": "analysis.schema.json",
        },
        "catalog_file": "01_sources.json",
        "catalog_field": "sources",
        "token_prefix": "S",
        "url_required": False,
        "final_name": "06_final_report.md",
        "gaps_field": None,
    },
    "reply": {
        "artifacts": {
            "01_issues.json": "issues.schema.json",
            "02_evidence.json": "evidence.schema.json",
        },
        "catalog_file": "02_evidence.json",
        "catalog_field": "evidence",
        "token_prefix": "E",
        "url_required": True,
        "final_name": "06_final_reply.md",
        "gaps_field": "gaps",
    },
}
AUDITS = {
    "04_citation_audit.json": "audit.schema.json",
    "04_format_audit.json": "audit.schema.json",
}


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"MISSING_ARTIFACT:{path.name}"
    except json.JSONDecodeError as e:
        return None, f"INVALID_JSON:{path.name}:{e.lineno}"


def check_schema(data, schema_path: Path, name: str):
    """간이 스키마: 최상위 required + 배열 타입 + 항목별 required + id 형식·중복."""
    errors = []
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return [f"SCHEMA:{name}: 최상위가 객체가 아님"]
    for key in schema.get("required", []):
        if key not in data:
            errors.append(f"SCHEMA:{name}: 최상위 필수 키 없음 '{key}'")
    arr_field = schema.get("array_field")
    id_pattern = schema.get("id_pattern")
    if arr_field and arr_field in data:
        items = data[arr_field]
        if not isinstance(items, list):
            errors.append(f"SCHEMA:{name}: '{arr_field}'가 배열이 아님")
        else:
            seen_ids = set()
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"SCHEMA:{name}: {arr_field}[{i}]가 객체가 아님")
                    continue
                for key in schema.get("item_required", []):
                    if key not in item:
                        errors.append(f"SCHEMA:{name}: {arr_field}[{i}] 필수 키 없음 '{key}'")
                item_id = item.get("id")
                if item_id is not None and id_pattern:
                    if not re.match(id_pattern, str(item_id)):
                        errors.append(f"SCHEMA:{name}: id 형식 위반 '{item_id}'")
                    if item_id in seen_ids:
                        errors.append(f"SCHEMA:{name}: id 중복 '{item_id}'")
                    seen_ids.add(item_id)
    return errors


def check_citations(draft: str, catalog: list, prefix: str):
    """초안의 인용 토큰 무결성 검사 (기형 토큰 포함)."""
    errors, warnings = [], []
    catalog_ids = {item.get("id") for item in catalog if isinstance(item, dict)}
    used = set(TOKEN_RE.findall(draft))
    malformed = {t for t in set(TOKEN_LIKE_RE.findall(draft)) if not ID_RE.match(t)}
    if malformed:
        errors.append(f"CITATION: 기형 인용 토큰 {sorted(malformed)}")
    wrong_prefix = {t for t in used if not t.startswith(prefix)}
    if wrong_prefix:
        errors.append(f"CITATION: 파이프라인과 다른 토큰 사용 {sorted(wrong_prefix)}")
    broken = {t for t in used if t.startswith(prefix)} - catalog_ids
    if broken:
        errors.append(f"CITATION: 카탈로그에 없는 토큰 인용 {sorted(broken)}")
    if not used:
        errors.append("CITATION: 초안에 인용 토큰이 하나도 없음")
    unused = catalog_ids - used
    if unused:
        warnings.append(f"CITATION: 인용되지 않은 카탈로그 항목 {sorted(unused)}")
    return errors, warnings


def check_domains(catalog: list, url_required: bool):
    """출처 URL이 공식 도메인 화이트리스트에 있는지 검사.

    URL 없는 출처: A라인(원문 파일 붙여넣기)은 warning(검증 불가 표시),
    B라인(근거)은 error — 근거는 반드시 출처 URL이 있어야 한다.
    """
    errors, warnings = [], []
    allow = json.loads((ROOT / "config" / "domains.json").read_text(encoding="utf-8"))["allow"]
    for item in catalog:
        if not isinstance(item, dict):
            continue
        url, item_id = item.get("url"), item.get("id")
        if not url:
            (errors if url_required else warnings).append(
                f"DOMAIN: {item_id} URL 없음" + ("" if url_required else " (검증 불가)"))
            continue
        host = urlparse(url).hostname or ""
        if not any(host == d or host.endswith("." + d) for d in allow):
            errors.append(f"DOMAIN: {item_id} 비허용 도메인 '{host}'")
    return errors, warnings


def check_sensitive(draft: str):
    """민감어 스캔 — 발견 시 재작성이 아니라 사람 검토로 보낸다."""
    terms = json.loads((ROOT / "config" / "sensitive_terms.json").read_text(encoding="utf-8"))["terms"]
    return [f"SENSITIVE: 민감어 '{t}' 포함" for t in terms if t in draft]


def check_gaps(catalog_data: dict, cfg: dict, draft: str):
    """근거 공백 처리 검사 (파이프라인 B 전용).

    - 근거가 0건이면 초안을 쓸 자격 자체가 없음 → 사람 검토 (hard)
    - gaps가 있으면 초안이 '확인 불가'를 명시해야 함 → 미명시 시 재작성 (revisable)
    """
    hard, revisable = [], []
    if cfg["gaps_field"] is None:
        return hard, revisable
    evidence = catalog_data.get(cfg["catalog_field"], [])
    gaps = catalog_data.get(cfg["gaps_field"], [])
    if isinstance(evidence, list) and len(evidence) == 0:
        hard.append("INSUFFICIENT_EVIDENCE: 검증된 근거 0건")
    if isinstance(gaps, list) and gaps and "확인 불가" not in draft:
        revisable.append(
            f"GAPS: 근거 공백 {len(gaps)}건이 있으나 초안에 '확인 불가' 명시 없음")
    return hard, revisable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--pipeline", required=True, choices=list(PIPELINES))
    ap.add_argument("--revision", type=int, default=0)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    cfg = PIPELINES[args.pipeline]
    schema_dir = ROOT / "schema"
    hard_errors, revisable, warnings = [], [], []

    # 1. 파이프라인 산출물 스키마 검사
    artifacts = {}
    for fname, schema in {**cfg["artifacts"], **AUDITS}.items():
        data, err = load_json(run_dir / fname)
        if err:
            hard_errors.append(err)
            continue
        hard_errors += check_schema(data, schema_dir / schema, fname)
        artifacts[fname] = data

    draft_path = run_dir / "03_draft.md"
    if not draft_path.exists():
        hard_errors.append("MISSING_ARTIFACT:03_draft.md")

    if hard_errors:
        decide(run_dir, cfg, "failed", hard_errors, warnings, args)
        return

    draft = draft_path.read_text(encoding="utf-8")
    catalog_data = artifacts[cfg["catalog_file"]]
    catalog = catalog_data[cfg["catalog_field"]]

    # 2~5. 결정론적 내용 검사
    errs, warns = check_citations(draft, catalog, cfg["token_prefix"])
    revisable += errs
    warnings += warns
    errs, warns = check_domains(catalog, cfg["url_required"])
    revisable += errs
    warnings += warns
    sensitive = check_sensitive(draft)
    gap_hard, gap_revisable = check_gaps(catalog_data, cfg, draft)
    revisable += gap_revisable

    # 6. 감사 verdict 종합
    verdicts = {f: artifacts[f].get("verdict") for f in AUDITS}
    escalated = [f"AUDIT: {f} → ESCALATE" for f, v in verdicts.items() if v == "ESCALATE"]
    revise_req = [f"AUDIT: {f} → REVISE" for f, v in verdicts.items() if v == "REVISE"]
    invalid_v = [f"AUDIT: {f} verdict 값 이상 '{v}'" for f, v in verdicts.items()
                 if v not in ("PASS", "REVISE", "ESCALATE")]
    if invalid_v:
        decide(run_dir, cfg, "failed", invalid_v, warnings, args)
        return

    # 판정 규칙 (우선순위 순)
    if sensitive or escalated or gap_hard:
        decide(run_dir, cfg, "human_review_required",
               sensitive + escalated + gap_hard, warnings, args)
    elif revisable or revise_req:
        if args.revision < 1:
            decide(run_dir, cfg, "revision_required", revisable + revise_req, warnings, args)
        else:
            decide(run_dir, cfg, "human_review_required",
                   ["MAX_REVISIONS_REACHED"] + revisable + revise_req, warnings, args)
    else:
        decide(run_dir, cfg, "completed", [], warnings, args)


def decide(run_dir: Path, cfg: dict, status: str, reasons: list, warnings: list, args):
    final = cfg["final_name"] if status == "completed" else None
    decision = {
        "pipeline": args.pipeline,
        "revision": args.revision,
        "status": status,
        "reasons": reasons,
        "warnings": warnings,
        "final": final,
    }
    (run_dir / "05_gate_decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    final_path = run_dir / cfg["final_name"]
    if status == "completed":
        # completed일 때만 final 생성 — 그 외 상태에서 final은 존재하지 않는다
        draft = (run_dir / "03_draft.md").read_text(encoding="utf-8")
        stamp = ("> ✅ 게이트 통과 (revision {rev}) — 본 문서는 AI 지원 초안으로 담당자"
                 " 최종 검토가 필요함\n\n").format(rev=args.revision)
        final_path.write_text(stamp + draft, encoding="utf-8")
    elif final_path.exists():
        # 재실행에서 판정이 뒤집힌 경우 이전 final을 남기지 않는다 (stale final 방지)
        final_path.unlink()
    print(json.dumps(decision, ensure_ascii=False, indent=2))
    sys.exit(0 if status == "completed" else 1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # 예기치 못한 예외도 판정 없이 죽지 않는다
        print(json.dumps({"status": "failed",
                          "reasons": [f"GATE_EXCEPTION: {type(e).__name__}: {e}"],
                          "final": None}, ensure_ascii=False, indent=2))
        sys.exit(1)
