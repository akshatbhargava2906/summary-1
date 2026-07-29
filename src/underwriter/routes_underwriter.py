import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import StreamingResponse
from src.pipeline import run
from src.client import generate_patient_summary

router = APIRouter(prefix="/underwriter", tags=["underwriter"])


def _run_stream(pairs: list[tuple[str, bytes]], questionnaire: dict) -> StreamingResponse:
    def stream():
        try:
            result = run(pairs, questionnaire)
            yield json.dumps(result["output"])
        except Exception as e:
            yield json.dumps({"error": str(e)})

    return StreamingResponse(stream(), media_type="application/json")


@router.post("/summarize-patient")
async def summarize_patient(patient_data: dict = Body(...)):
    try:
        summary = generate_patient_summary(patient_data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"summary": summary}


@router.post("/analyse")
async def analyse(
    files: list[UploadFile] = File(...),
    patient_data: str = Form(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    try:
        questionnaire = json.loads(patient_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="patient_data is not valid JSON.")
    pairs = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{f.filename} is not a PDF.")
        pairs.append((f.filename, await f.read()))

    return _run_stream(pairs, questionnaire)