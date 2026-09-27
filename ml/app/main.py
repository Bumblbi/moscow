import math
import os
import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from catboost import CatBoostRegressor
except ImportError:
    CatBoostRegressor = None


class Features(BaseModel):
    current_delay_min: float
    speed: float
    distance_to_stop_km: float
    hour: int = Field(ge=0, le=23)
    historical_delay_min: float
    dwell_seconds: float = 0.0
    horizon_min: int = Field(ge=10, le=15)
    model_features: dict[str, float | None] | None = None


app = FastAPI(title="Transport predictor ML service", version="1.0.0")
model_path = Path(os.getenv("MODEL_PATH", "models/delay_model.cbm"))
metadata_path = Path(os.getenv("MODEL_METADATA_PATH", "models/competition_delay_model.metadata.json"))
model = None
feature_columns: list[str] = []
model_version = "baseline-v1"
if CatBoostRegressor and model_path.exists():
    model = CatBoostRegressor()
    model.load_model(model_path)
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        feature_columns = list(metadata.get("feature_columns", []))
        model_version = str(metadata.get("model_version", "catboost-v1"))
    elif model.feature_names_:
        feature_columns = list(model.feature_names_)


def heuristic(features: Features) -> tuple[float, float, str]:
    congestion = max(0.0, 20.0 - features.speed) / 20.0
    dwell = min(features.dwell_seconds / 180.0, 1.0)
    peak = 0.3 if features.hour in {7, 8, 9, 17, 18, 19} else 0.0
    raw = -1.5 + 0.42 * features.current_delay_min + 1.25 * congestion + 0.55 * dwell + peak
    probability = 1 / (1 + math.exp(-raw))
    delay = max(0.0, features.current_delay_min + congestion * 4 + dwell * 2 + peak)
    reason = (
        "длительная стоянка"
        if dwell >= 0.5
        else "аномально низкая скорость"
        if features.speed < 12
        else "накопленное отклонение от графика"
        if features.current_delay_min >= 3
        else "рисковый паттерн не выявлен"
    )
    return probability, delay, reason


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "model_version": model_version,
        "feature_count": len(feature_columns),
    }


@app.post("/predict")
def predict(features: Features) -> dict:
    if model and feature_columns:
        supplied = features.model_features or {}
        row = [[float(supplied[name]) if supplied.get(name) is not None else math.nan for name in feature_columns]]
        delay_seconds = float(model.predict(row)[0])
        delay = delay_seconds / 60.0
        probability = 1 / (1 + math.exp(-((delay_seconds - 180.0) / 60.0)))
        reason = "паттерн CatBoost"
        version = model_version
    else:
        probability, delay, reason = heuristic(features)
        version = "baseline-v1"
    return {
        "probability": round(probability, 4),
        "predicted_delay_min": round(delay, 2),
        "reason": reason,
        "model_version": version,
    }
