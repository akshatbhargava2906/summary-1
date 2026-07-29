from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.underwriter.routes_underwriter import router as underwriter_router

app = FastAPI(title="Medical Risk Analyzer API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST", "GET"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(underwriter_router)