import os
import json
import time
import requests
from requests.auth import HTTPBasicAuth
from json_repair import repair_json
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = os.getenv("AI_CORE_BASE_URL", "").rstrip("/")
_AUTH_URL = os.getenv("AI_CORE_AUTH_URL", "")
_CLIENT_ID = os.getenv("AI_CORE_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("AI_CORE_CLIENT_SECRET", "")
_RESOURCE_GROUP = os.getenv("AI_CORE_RESOURCE_GROUP", "default")
_DEPLOYMENT_ID = os.getenv("AI_CORE_DEPLOYMENT_ID", "")

_token_cache: dict = {"token": None, "expires_at": 0.0}


#  Auth 

def _get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = requests.post(
        _AUTH_URL,
        auth=HTTPBasicAuth(_CLIENT_ID, _CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        verify=False,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    return _token_cache["token"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "AI-Resource-Group": _RESOURCE_GROUP,
        "Content-Type": "application/json",
    }


#  Core invoke ─

def _invoke_claude(body: dict, timeout: int = 120) -> dict:
    url = f"{_BASE_URL}/v2/inference/deployments/{_DEPLOYMENT_ID}/invoke"
    resp = requests.post(url, headers=_headers(), json=body, verify=False, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_json(raw: str) -> dict:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON found. Raw start: {raw[:200]}")
    raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(repair_json(raw))


#  Claude calls 

def extract_indicators(pdf_b64: str) -> dict:
    system = """You are a medical document extraction assistant.
First identify the document type, then extract all measurable health indicators.
Return ONLY valid JSON — no explanation, no markdown fences. Notes must be 5 words max:
{
  "doc_type": "blood|xray|ecg|unknown",
  "patient_name": "string",
  "report_date": "string",
  "indicators": [
    {
      "name": "string",
      "value": "string",
      "unit": "string",
      "reference_range": "string",
      "status": "normal|abnormal|critical",
      "note": "max 5 words"
    }
  ]
}
doc_type rules:
- blood: CBC, metabolic panel, lipid panel, blood test, and any other blood-based lab test
- xray: chest X-ray, bone X-ray, radiograph, and any other radiology imaging
- ecg: electrocardiogram, ECG, EKG, cardiac rhythm, and any other heart rhythm test
- unknown: whichever lab report type is not blood, xray, or ecg
Status rules:
- normal: value within reference range
- abnormal: value outside reference range
- critical: outside range AND marked H* / L* / CRITICAL / PANIC"""

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 8192,
        "system": system,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": "Identify the document type and extract all health indicators. Return the JSON."},
                ],
            }
        ],
    }

    raw = _invoke_claude(body)["content"][0]["text"]
    return _parse_json(raw)


def generate_patient_summary(questionnaire: dict) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": (
            "You are an insurance intake assistant. Summarize the applicant's personal, "
            "physical, occupational, medical history, family history, and financial profile "
            "in a concise plain-English paragraph for an underwriter. Never give a coverage "
            "or pricing decision — only observations."
        ),
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Applicant intake data (JSON):\n{json.dumps(questionnaire, indent=2)}\n\n"
                    "Write a short narrative summary of this applicant."
                ),
            }
        ],
    }
    return _invoke_claude(body, timeout=60)["content"][0]["text"]


def generate_analysis(risk_score: int, risk_tier: str, flagged: list, questionnaire: dict = None) -> str:
    lines = "\n".join(
        f"- [{i.get('doc_type', 'unknown').upper()}] {i['name']}: {i['value']} {i['unit']} "
        f"(ref: {i['reference_range']}) — {i.get('note', '')}"
        for i in flagged
    )

    q_context = ""
    if questionnaire:
        smoking = questionnaire.get("smoking", {})
        history = questionnaire.get("family_history", [])
        claims = questionnaire.get("insurance", {}).get("previous_claims", "")
        q_context = (
            f"\nPatient Background:"
            f"\n- Smoking: {smoking.get('status', 'unknown')} ({smoking.get('pack_years', 'N/A')} pack-years)"
            f"\n- Family history: {', '.join(history) if history else 'None reported'}"
            f"\n- Previous claims: {claims if claims else 'None'}"
        )

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "system": "You are a clinical risk analyst for an insurance underwriter. Write plain-English summaries. Never give a yes/no claim decision — only observations.",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Risk Score: {risk_score}/100\nRisk Tier: {risk_tier}"
                    f"{q_context}\n\n"
                    f"Flagged Indicators:\n{lines}\n\n"
                    "Return exactly two sections:\n"
                    "SUMMARY — 2 to 5 short paragraphs, one blank line between each, "
                    "each covering a distinct theme (e.g. cardiovascular risk, metabolic risk, "
                    "hematologic findings, cardiac findings, overall assessment). Only include "
                    "themes actually present in the flagged indicators.\n"
                    "FLAGGED INDICATORS"
                ),
            }
        ],
    }

    return _invoke_claude(body, timeout=60)["content"][0]["text"]