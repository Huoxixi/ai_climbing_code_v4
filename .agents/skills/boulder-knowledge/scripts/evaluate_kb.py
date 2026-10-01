"""Read-only development retrieval evaluation; never a video/answer accuracy test."""
import hashlib
import json
from pathlib import Path
import sys

import kb


def evaluate(lib, suite):
    kb.require(suite.get("schema_version") == 1, "evaluation schema unsupported")
    kb.require(suite.get("provenance") == "current_agent_authored_development_set"
               and suite.get("independent") is False, "evaluation provenance unsupported")
    kb.text_field(suite, "suite_id", "evaluation")
    cases = kb.rows(suite, "cases", "evaluation")
    kb.require(bool(cases), "evaluation cases empty")
    known = {u["id"] for u in lib["units"]}
    seen, results = set(), []
    for case in cases:
        cid = kb.text_field(case, "id", "case")
        kb.require(cid not in seen, f"duplicate evaluation case {cid}")
        seen.add(cid)
        query = kb.text_field(case, "query", cid)
        kb.text_field(case, "answer_check", cid)
        required = set(kb.strings(case, "required_units", cid, False))
        accepted = set(kb.strings(case, "accepted_units", cid, False))
        kb.require(required <= accepted <= known, f"{cid}: invalid expected units")
        kb.require(bool(required) == bool(accepted), f"{cid}: ambiguous empty expectation")
        found = [r["id"] for r in kb.search(lib, query, limit=3)]
        results.append({"id": cid, "query": query, "found": found,
                        "required": sorted(required), "missing": sorted(required - set(found)),
                        "outside_accepted": [u for u in found if u not in accepted],
                        "retrieval_ok": required <= set(found) if required else not found,
                        "automatic_video_disabled": kb.search(lib, query, purpose="video") == []})
    positives = [r for r in results if r["required"]]
    negatives = [r for r in results if not r["required"]]
    total_returned = sum(len(r["found"]) for r in positives)
    noise = sum(len(r["outside_accepted"]) for r in positives)
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "suite_id": suite["suite_id"], "scope": "development_retrieval_only",
        "independent": False, "answer_quality_measured": False, "real_video_used": False,
        "suite_sha256": hashlib.sha256(canonical(suite)).hexdigest(),
        "knowledge_sha256": hashlib.sha256(canonical({"units": lib["units"], "sources": lib["sources"]})).hexdigest(),
        "retriever_sha256": hashlib.sha256(Path(kb.__file__).read_bytes()).hexdigest(),
        "metrics": {
            "cases": len(results), "positive_cases": len(positives),
            "all_required_in_top3": sum(r["retrieval_ok"] for r in positives),
            "negative_cases": len(negatives), "empty_for_negative": sum(r["retrieval_ok"] for r in negatives),
            "positive_returned_candidates": total_returned, "outside_accepted_candidates": noise,
            "video_disabled_cases": sum(r["automatic_video_disabled"] for r in results)
        },
        "results": results,
        "limitations": ["同一编写者创建并用于调参的开发集，不是独立留出集。",
                        "期望集合不是所有合法关联的穷举；集合外命中仅作为本次噪声检查。",
                        "未调用回答模型；answer_check 是人工复核要求，不是已通过的答案评分。"]
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        lib = kb.load_library(kb.DEFAULT_ROOT)
        kb.validate(lib)
        suite = kb.load_json(kb.safe_path(lib["root"], "quality/retrieval-cases.json"))
        print(json.dumps(evaluate(lib, suite), ensure_ascii=False, indent=2))
        return 0
    except (kb.InvalidKnowledge, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
