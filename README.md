# Medical Risk Analyzer API

An AI-powered insurance underwriting backend built on Claude via SAP AI Core.
Given a patient questionnaire and uploaded medical-report PDFs, it extracts
clinical indicators, computes a deterministic risk score, and generates an
AI-written plain-English summary for an underwriter.

> **Status:** backend-only. There is currently no applicant intake flow, no
> case persistence, and no frontend in this repository — see
> [Known Limitations](#known-limitations).

---

## Architecture

```
                POST /underwriter/summarize-patient
                POST /underwriter/analyse
                              │
                              ▼
                    api.py (FastAPI)
                              │
                              ▼
              src/underwriter/routes_underwriter.py
                              │
                              ▼
                      src/pipeline.py  ── run()
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
            src/client.py  src/risk_scorer.py  src/cache.py
            (Claude via
             SAP AI Core)
```

---

## API Endpoints

| Method | URL                             | Description                                                        |
|--------|----------------------------------|----------------------------------------------------------------------|
| GET    | `/health`                       | Liveness check                                                      |
| GET    | `/docs`                         | Interactive Swagger UI                                              |
| POST   | `/underwriter/summarize-patient`| AI plain-English summary of raw questionnaire JSON (no documents)   |
| POST   | `/underwriter/analyse`          | Full pipeline: PDF extraction + deterministic scoring + AI analysis |

There is no persistence layer — every request is self-contained. Each call
to `/underwriter/analyse` re-uploads the documents and questionnaire; nothing
is stored server-side beyond the indicator cache described below.

### POST `/underwriter/summarize-patient`

```
Content-Type: application/json
Body: the questionnaire object (see schema below)
```

Returns:

```json
{ "summary": "Plain-English narrative paragraph..." }
```

### POST `/underwriter/analyse`

Accepts multipart form-data:

```
Content-Type: multipart/form-data
Field name: files          (repeat for each PDF)
Field name: patient_data   (JSON string, see schema below)
```

Response is streamed as a single JSON object:

```json
{
  "patient": { "name": "John Doe", "age": "54", "gender": "Male", "location": "Singapore" },
  "insurance": {
    "current_coverage": "Life + Critical Illness",
    "coverage_amount": "SGD 500,000",
    "previous_claims": "1 claim (2021)",
    "smoking_status": "Former Smoker",
    "pack_years": "15",
    "family_history": ["Hypertension", "Type 2 Diabetes"]
  },
  "risk_assessment": {
    "score": 82,
    "tier": "Risk",
    "indicator_points": 68,
    "questionnaire_points": 14,
    "total_indicators": 14,
    "flagged_count": 8
  },
  "summary": [
    "Cardiovascular Risk Profile: This applicant presents with a significantly adverse lipid profile...",
    "Metabolic and Insulin Resistance Findings: The applicant demonstrates clear evidence of pre-diabetes...",
    "Overall Assessment: This applicant presents a convergence of multiple modifiable and non-modifiable risk factors..."
  ],
  "flagged_indicators": [
    {
      "source": "blood",
      "name": "LDL Cholesterol",
      "value": "160",
      "unit": "mg/dL",
      "reference_range": "< 130 mg/dL",
      "status": "abnormal",
      "note": "Elevated; above desirable level"
    }
  ],
  "docs_processed": {
    "successful": ["blood_panel.pdf", "chest_xray.pdf"],
    "failure": []
  }
}
```

`summary` is a list of narrative paragraphs (markdown bold markers and any
trailing horizontal-rule artifacts from the model's raw output are stripped
server-side — see [Notes on the AI summary](#notes-on-the-ai-summary)).

### `patient_data` schema

No strict schema is enforced server-side — extra fields are accepted and
either ignored, displayed, or fed into scoring/AI prompts depending on which
endpoint you call.

```json
{
  "patient_name": "John Doe",
  "age": "54",
  "gender": "Male",
  "location": "Singapore",
  "smoking": { "status": "Former Smoker", "pack_years": "15" },
  "family_history": ["Hypertension", "Type 2 Diabetes"],
  "insurance": {
    "current_coverage": "Life",
    "coverage_amount": "500000",
    "previous_claims": "1 claim"
  }
}
```

- `age`, `gender`, `location` — shown in the `patient` block of the response.
- `smoking`, `family_history`, `insurance.previous_claims` — the only fields
  the deterministic risk scorer reads (see below).
- Any other fields you include are simply echoed back where relevant or
  ignored — they are not validated.

---

## Risk Scoring

Scoring is fully deterministic — no LLM involved.

### Clinical indicators (extracted from uploaded medical documents)

| Status   | Points each | Cap    |
|----------|-------------|--------|
| abnormal | +8          | max 40 |
| critical | +20         | max 60 |

### Questionnaire adjustments (from `patient_data`)

| Factor                        | Points |
|--------------------------------|--------|
| Current smoker                 | +10    |
| Former smoker                  | +5     |
| 2+ family history conditions   | +8     |
| Previous insurance claims      | +5     |

Combined total is capped at 100.

### Risk tiers

| Score    | Tier   |
|----------|--------|
| 0 – 49   | Normal |
| 50 – 74  | High   |
| 75 – 100 | Risk   |

---

## Notes on the AI summary

`generate_analysis()` (in `src/client.py`) asks Claude to return a `SUMMARY`
section (2–5 short paragraphs) followed by a `FLAGGED INDICATORS` section.
`_extract_summary()` (in `src/pipeline.py`) parses out just the `SUMMARY`
paragraphs, strips any markdown bold (`**`) the model adds around paragraph
headings, and treats markdown horizontal rules (lines of only `-`) as
paragraph separators rather than content — so they never leak into the
returned list as a stray `"---"` entry.

---

## Project Structure

```
summary-1/
├── api.py                              # FastAPI app setup + router wiring
├── manifest.yaml                       # CF deployment config
├── Procfile
├── runtime.txt
├── requirements.txt
├── .env.example
├── test_api.py                         # Manual SAP AI Core connectivity check
└── src/
    ├── client.py                       # Claude via SAP AI Core (OAuth2)
    ├── pipeline.py                     # run() — parallel extraction, scoring, analysis
    ├── risk_scorer.py                  # Deterministic scoring and tier logic
    ├── pdf_utils.py                    # bytes_to_base64
    ├── cache.py                        # JSON cache (.cache/{patient_id}/)
    └── underwriter/
        └── routes_underwriter.py       # /underwriter/* endpoints
```

---

## Local Setup

```bash
git clone <repo-url>
cd summary-1
pip install -r requirements.txt
cp .env.example .env        # fill in SAP AI Core credentials
uvicorn api:app --reload
```

Then open `http://127.0.0.1:8000/docs` for the interactive Swagger UI, or
hit the endpoints directly (e.g. with `curl` or Postman) — there is no
bundled frontend.

## Environment Variables

```
AI_CORE_BASE_URL=
AI_CORE_AUTH_URL=
AI_CORE_CLIENT_ID=
AI_CORE_CLIENT_SECRET=
AI_CORE_RESOURCE_GROUP=
AI_CORE_DEPLOYMENT_ID=
AI_CORE_EMBEDDING_ID=
```

`test_api.py` additionally checks for an Azure embedding deployment
(`AZURE_EMBEDDING_ENDPOINT`, `AZURE_EMBEDDING_API_KEY`,
`AZURE_EMBEDDING_DEPLOYMENT`, `AZURE_EMBEDDING_API_VERSION`), but nothing in
`src/` currently uses embeddings — this is exercised only by the manual test
script.

---

## Caching

Extracted clinical indicators are cached as JSON under `.cache/{patient_id}/`
after the first run against a given set of filenames. Subsequent requests
with the same filenames load from cache, skipping the Claude extraction
calls entirely.

The patient ID is a hash of the sorted uploaded filenames — **not** file
content, so re-uploading a different file under a previously-used filename
will incorrectly hit the cache.

Cache is ephemeral on Cloud Foundry (cleared on restart). `.cache/` and
`.chroma/` are excluded from version control via `.gitignore`.

---

## Deployment (SAP BTP Cloud Foundry)

App name on CF: **`insurance-risk-analyser`** (per `manifest.yaml`), deployed at
`https://insurance-risk-analyser.cfapps.eu10-004.hana.ondemand.com`.

### First-time setup

```bash
cf login -a https://api.cf.eu10-004.hana.ondemand.com --sso
```

Select org `Fioneer - Insurance Verticals - Dev_poc-event-mesh-tn1hxef4`
and space `axa-ml-app`. Then:

```bash
cf push
```

After the first push, set credentials:

```bash
cf set-env insurance-risk-analyser AI_CORE_BASE_URL "..."
cf set-env insurance-risk-analyser AI_CORE_AUTH_URL "..."
cf set-env insurance-risk-analyser AI_CORE_CLIENT_ID "..."
cf set-env insurance-risk-analyser AI_CORE_CLIENT_SECRET "..."
cf set-env insurance-risk-analyser AI_CORE_RESOURCE_GROUP "..."
cf set-env insurance-risk-analyser AI_CORE_DEPLOYMENT_ID "..."
cf restage insurance-risk-analyser
```

### Redeploying after code changes

```bash
cf login -a https://api.cf.eu10-004.hana.ondemand.com --sso   # if session expired
cf push
```

### Status and logs

```bash
cf app insurance-risk-analyser              # status, memory, instances
cf logs insurance-risk-analyser --recent    # last logs
cf logs insurance-risk-analyser             # live log stream
```

### Scaling

```bash
cf scale insurance-risk-analyser -i 2    # 2 instances
cf scale insurance-risk-analyser -m 1G   # increase memory
```

---

## Known Limitations

- **No frontend.** There is no bundled UI in this repository — interact via
  `/docs` or direct HTTP calls.
- **No applicant/case-store layer.** There is no claim-submission flow,
  identity verification, or server-side case persistence (`.cases/`) —
  every `/underwriter/*` call is stateless and self-contained per request.
- **No authentication/role separation** on any endpoint — anyone with the
  API URL can call it. Handled outside this codebase per current product
  direction.
- TLS certificate verification is disabled (`verify=False`) on all SAP AI
  Core HTTP calls in `src/client.py` and `test_api.py`.
- The indicator cache keys on uploaded **filenames only**, not file content
  (see [Caching](#caching)).
