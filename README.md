# Medical Risk Analyzer API

An AI-powered insurance underwriting pipeline built on Claude via SAP AI Core.
The system is split into two roles that mirror the real workflow:

- **Applicant** — fills out a claim form, uploads supporting medical documents,
  and gets an AI identity-verification check comparing the form against the
  documents before submitting.
- **Underwriter** — loads a submitted case by reference, reviews the applicant's
  data and documents (read-only, nothing re-entered or re-uploaded), and runs
  an AI-generated summary plus a full clinical risk analysis.

The two roles are connected by a lightweight server-side case store — no
database, just JSON + the original PDFs written to disk per submission.

---

## Architecture

```
Applicant (claimform.html)                Underwriter (underwriterreview.html)
        │                                              │
        │ POST /applicant/verify-identity              │ GET  /underwriter/cases
        │ POST /applicant/submit-claim                 │ GET  /underwriter/cases/{ref}
        │                                               │ POST /underwriter/cases/{ref}/summarize-patient
        │                                               │ POST /underwriter/cases/{ref}/analyse
        ▼                                               ▼
                    api.py (FastAPI, role-scoped routers)
                              │
              ┌───────────────┼────────────────┐
              ▼                ▼                ▼
      src/applicant/    src/casestore.py   src/underwriter/
      (verify.py,       (.cases/{ref}/     (routes_underwriter.py)
      routes_applicant  meta.json +
      .py)              documents/)
              │
              ▼
      src/client.py → Claude via SAP AI Core
      src/pipeline.py, src/risk_scorer.py
```

---

## API Endpoints

| Method | URL                                                | Description                                              |
|--------|-----------------------------------------------------|------------------------------------------------------------|
| GET    | `/health`                                          | Liveness check                                            |
| GET    | `/docs`                                            | Interactive Swagger UI                                    |
| POST   | `/applicant/verify-identity`                       | Compare form data against documents, no persistence       |
| POST   | `/applicant/submit-claim`                          | Re-verify + persist a case; returns a claim reference      |
| GET    | `/underwriter/cases`                               | List all submitted cases                                  |
| GET    | `/underwriter/cases/{claim_ref}`                   | Full case detail — form data + verification result        |
| GET    | `/underwriter/cases/{claim_ref}/documents/{file}`  | Serves a stored document                                   |
| POST   | `/underwriter/cases/{claim_ref}/summarize-patient` | AI plain-English summary of a stored case                 |
| POST   | `/underwriter/cases/{claim_ref}/analyse`           | Full clinical extraction + risk score for a stored case    |
| POST   | `/underwriter/summarize-patient`                   | Generic summary endpoint (no case, standalone testing)     |
| POST   | `/underwriter/analyse`                             | Generic analysis endpoint (no case, standalone testing)    |

### POST `/applicant/verify-identity` and `/applicant/submit-claim`

Both accept multipart form-data:

```
Content-Type: multipart/form-data
Field name: files          (repeat for each PDF)
Field name: patient_data   (JSON string, see schema below)
```

`verify-identity` returns the comparison only, without saving anything:

```json
{
  "documents": [
    {
      "filename": "report.pdf",
      "comparisons": [
        { "field": "patient_name", "form_value": "John Doe", "document_value": "John Doe", "matched": true },
        { "field": "date_of_birth", "form_value": "1972-03-10", "document_value": "1972-03-10", "matched": true },
        { "field": "gender", "form_value": "Male", "document_value": "Male", "matched": true }
      ],
      "has_mismatch": false
    }
  ],
  "has_any_mismatch": false
}
```

`submit-claim` re-runs the same verification server-side (never trusts a
client-supplied result), persists the case, and returns:

```json
{ "claim_ref": "CLM-4782289653", "verification": { "...": "same shape as above" } }
```

### `patient_data` schema

No strict schema is enforced server-side — extra fields are accepted and
either ignored, displayed, or fed into scoring/AI prompts depending on which
endpoint you call. A payload exercising the full pipeline:

```json
{
  "patient_name": "John Doe",
  "age": "54",
  "date_of_birth": "1972-03-10",
  "gender": "Male",
  "location": "Singapore",
  "relationship": "self",
  "phone": "+65 9123 4567",
  "email": "john.doe@email.com",
  "address": "12 Orchard Road, Singapore, 238841",
  "policy_number": "POL-482913",
  "member_id": "MBR-100234",
  "smoking": { "status": "Former Smoker", "pack_years": "15" },
  "family_history": ["Hypertension", "Type 2 Diabetes"],
  "insurance": {
    "current_coverage": "Life",
    "coverage_amount": "500000",
    "previous_claims": "1 claim"
  },
  "claim_type": "hospitalization",
  "treatment_date": "2026-07-10",
  "provider_name": "Singapore General Hospital",
  "diagnosis": "Acute Appendicitis",
  "claim_amount": "8500.00",
  "previous_insurance": "no",
  "previous_insurance_details": ""
}
```

- `patient_name`, `date_of_birth`, `gender` — the only three fields identity
  verification compares against the uploaded documents.
- `age`, `gender`, `location` — shown in the risk analysis "Patient Details" panel.
- `smoking`, `family_history`, `insurance.previous_claims` — the only fields
  the deterministic risk scorer reads (see below). **`claimform.html`'s wizard
  does not currently collect these** — submissions from the applicant UI will
  score on clinical indicators alone until the intake form is extended.
- Everything else (`relationship`, `phone`, `email`, `address`, `policy_number`,
  `member_id`, `claim_type`, `treatment_date`, `provider_name`, `diagnosis`,
  `claim_amount`, `previous_insurance*`) is display-only, shown on the
  underwriter's case-detail grid.

### POST `/underwriter/cases/{claim_ref}/analyse` (and the generic `/underwriter/analyse`)

Same response shape either way — the case-backed version just reads
previously-stored data instead of requiring a new upload:

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
  "summary": "Patient presents with multiple cardiovascular risk factors...",
  "flagged_indicators": [
    {
      "source": "blood",
      "name": "LDL Cholesterol",
      "value": "4.8",
      "unit": "mmol/L",
      "reference_range": "< 3.4 mmol/L",
      "status": "critical",
      "note": "Significantly elevated; statin therapy indicated"
    }
  ]
}
```

---

## Risk Scoring

Scoring is fully deterministic — no LLM involved.

### Clinical indicators (extracted from uploaded medical documents)

| Status   | Points each | Cap    |
|----------|-------------|--------|
| abnormal | +8          | max 40 |
| critical | +20         | max 60 |

### Questionnaire adjustments (from `patient_data`)

| Factor                       | Points |
|------------------------------|--------|
| Current smoker                | +10    |
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

## Frontend Pages

Two standalone static HTML files, no build step — just open in a browser and
point the API URL field at a running backend.

- **`claimform.html`** — applicant intake wizard: Personal & Policy Info →
  Claim Details → Documents → Review (with in-line AI identity verification
  and a link back to correct mismatches) → Confirmation. On submit, calls
  `/applicant/submit-claim` and displays the returned claim reference.
- **`underwriterreview.html`** — underwriter case dashboard. Loads a case by
  reference (or pick from a "recent submissions" list), shows the applicant's
  data/documents/verification result read-only, and runs the AI summary and
  clinical analysis against the stored case. The risk analysis pre-fetches
  automatically as soon as a case loads — the button stays disabled
  ("Preparing Analysis…") while extraction runs in the background, then
  flips to "View Risk Analysis" for an instant, no-wait open.

---

## Project Structure

```
risk-summary/
├── api.py                          # FastAPI app setup + router wiring only
├── manifest.yaml                   # CF deployment config
├── Procfile
├── runtime.txt
├── requirements.txt
├── .env.example
├── claimform.html                  # Applicant-facing intake + submission
├── underwriterreview.html          # Underwriter-facing case review
├── test_api.py                     # Manual SAP AI Core connectivity check
└── src/
    ├── client.py                   # Claude via SAP AI Core (OAuth2)
    ├── pipeline.py                 # run() — parallel extraction, scoring, analysis
    ├── risk_scorer.py              # Deterministic scoring and tier logic
    ├── pdf_utils.py                # bytes_to_base64
    ├── cache.py                    # JSON cache (.cache/{patient_id}/)
    ├── casestore.py                # Case persistence (.cases/{claim_ref}/)
    ├── applicant/
    │   ├── verify.py               # Identity extraction + comparison
    │   └── routes_applicant.py     # /applicant/* endpoints
    └── underwriter/
        └── routes_underwriter.py   # /underwriter/* endpoints
```

---

## Local Setup

```bash
git clone <repo-url>
cd risk-summary
pip install -r requirements.txt
cp .env.example .env        # fill in SAP AI Core credentials
uvicorn api:app --reload
```

Then open `claimform.html` and `underwriterreview.html` directly in a
browser — each has an API URL field defaulting to `http://127.0.0.1:8000`.

## Environment Variables

```
AI_CORE_BASE_URL=
AI_CORE_AUTH_URL=
AI_CORE_CLIENT_ID=
AI_CORE_CLIENT_SECRET=
AI_CORE_RESOURCE_GROUP=
AI_CORE_DEPLOYMENT_ID=
```

---

## Caching

Extracted clinical indicators are cached as JSON under `.cache/{patient_id}/`
after the first run against a given document set. Subsequent requests for the
same patient load from cache, skipping the Claude extraction calls entirely.
The patient ID is derived from the first uploaded filename's stem.

Cache is ephemeral on Cloud Foundry (cleared on restart). `.cache/` and
`.chroma/` are excluded from version control via `.gitignore`.

## Case Storage

Every `/applicant/submit-claim` call writes a case to `.cases/{claim_ref}/`:
a `meta.json` (form data + identity-verification result) and a `documents/`
subfolder with the original uploaded PDFs. The underwriter endpoints read
this directly — nothing is re-uploaded. Path-traversal guards are applied to
both the claim reference and document filename on every read.

> **Note:** unlike `.cache/`, `.cases/` is not currently listed in
> `.gitignore` — add `.cases/` there if submitted case data (even synthetic
> test submissions) shouldn't be tracked in git. Cases are also ephemeral on
> Cloud Foundry the same way the cache is, since both live on local disk.

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

- No authentication/role separation between the applicant and underwriter
  endpoints — anyone with the API URL can hit either role's routes. Handled
  outside this codebase per current product direction.
- Underwriting decision controls (Approve / Request More Information /
  Decline) exist in `underwriterreview.html` but are not wired to anything.
- The claim-intake form (`claimform.html`) doesn't collect `smoking`,
  `family_history`, or `insurance.previous_claims` — submissions through the
  applicant UI will always score 0 questionnaire points until the form is
  extended to capture them.
