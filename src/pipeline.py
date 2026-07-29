import hashlib
from concurrent.futures import ThreadPoolExecutor
from src.pdf_utils import bytes_to_base64
from src.client import extract_indicators, generate_analysis
from src.risk_scorer import score_report
from src.cache import save_cache, load_cache


def _cache_key(files: list[tuple[str, bytes]]) -> str:
    names = "|".join(sorted(f[0] for f in files))
    return hashlib.sha256(names.encode()).hexdigest()[:20]


def _extract_summary(analysis_text: str) -> list[str]:
    if not analysis_text:
        return []
    lines = analysis_text.splitlines()
    in_summary = False
    paragraphs = []
    current = []
    for line in lines:
        clean = line.strip().lstrip("#*_ ").rstrip(":").upper()
        if clean == "SUMMARY":
            in_summary = True
            continue
        if in_summary:
            if clean in ("FLAGGED INDICATORS", "RECOMMENDATIONS"):
                break
            if not line.strip():
                if current:
                    paragraphs.append(" ".join(current).strip())
                    current = []
            else:
                current.append(line.strip())
    if current:
        paragraphs.append(" ".join(current).strip())
    return paragraphs


def _build_output(result: dict, questionnaire: dict, analysis_text: str, docs_processed: list) -> dict:
    insurance = questionnaire.get("insurance", {})
    smoking = questionnaire.get("smoking", {})
    return {
        "patient": {
            "name": questionnaire.get("patient_name", ""),
            "age": questionnaire.get("age", ""),
            "gender": questionnaire.get("gender", ""),
            "location": questionnaire.get("location", ""),
        },
        "insurance": {
            "current_coverage": insurance.get("current_coverage", ""),
            "coverage_amount": insurance.get("coverage_amount", ""),
            "previous_claims": insurance.get("previous_claims", ""),
            "smoking_status": smoking.get("status", ""),
            "pack_years": smoking.get("pack_years", ""),
            "family_history": questionnaire.get("family_history", []),
        },
        "risk_assessment": {
            "score": result["score"],
            "tier": result["tier"],
            "indicator_points": result["indicator_pts"],
            "questionnaire_points": result["questionnaire_pts"],
            "total_indicators": result["total"],
            "flagged_count": result["flagged_count"],
        },
        "summary": _extract_summary(analysis_text),
        "flagged_indicators": [
            {
                "name": ind.get("name", ""),
                "value": ind.get("value", ""),
                "unit": ind.get("unit", ""),
                "reference_range": ind.get("reference_range", ""),
                "status": ind.get("status", ""),
                "note": ind.get("note", ""),
                "source": ind.get("doc_type", ""),
            }
            for ind in result.get("flagged", [])
        ],
        "docs_processed": docs_processed,
    }


def _extract_one(filename: str, data: bytes):
    try:
        extraction = extract_indicators(bytes_to_base64(data))
        return filename, extraction, None
    except Exception as e:
        return filename, None, str(e)


def run(files: list[tuple[str, bytes]], questionnaire: dict) -> dict:
    patient_id = _cache_key(files)

    cached = load_cache(patient_id)
    if cached:
        all_indicators = cached["indicators"]
        docs_processed = {"successful": cached["filenames"], "failure": []}
    else:
        with ThreadPoolExecutor(max_workers=min(len(files), 8)) as executor:
            results = list(executor.map(lambda pair: _extract_one(*pair), files))

        all_indicators = []
        successful = []
        failure = []
        for filename, extraction, error in results:
            if error is not None:
                failure.append({"filename": filename, "error": error})
                continue
            indicators = extraction.get("indicators", [])
            for ind in indicators:
                ind["doc_type"] = extraction.get("doc_type", "medical")
            all_indicators.extend(indicators)
            successful.append(filename)

        docs_processed = {"successful": successful, "failure": failure}
        if not failure:
            save_cache(patient_id, successful, all_indicators)

    result = score_report(all_indicators, questionnaire)
    analysis_text = generate_analysis(result["score"], result["tier"], result["flagged"], questionnaire)

    return {
        "output": _build_output(result, questionnaire, analysis_text, docs_processed),
        "result": result,
        "questionnaire": questionnaire,
        "analysis_text": analysis_text,
        "docs_processed": docs_processed,
    }