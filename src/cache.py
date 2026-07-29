import json
from pathlib import Path

CACHE_PATH = Path(".cache")

def save_cache(patient_id: str, filenames: list, indicators: list):
    folder = CACHE_PATH / patient_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "indicators.json").write_text(json.dumps({"filenames": filenames, "indicators": indicators}))

def load_cache(patient_id: str) -> dict | None:
    folder = CACHE_PATH / patient_id
    ind_file = folder / "indicators.json"
    if not ind_file.exists():
        return None
    return json.loads(ind_file.read_text())