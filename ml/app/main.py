import math
import os
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


app = FastAPI(title="Transport predictor ML service", version="1.0.0")
model_path = Path(os.getenv("MODEL_PATH", "models/delay_model.cbm"))
model = None
if CatBoostRegressor and model_path.exists():
    model = CatBoostRegressor()
    model.load_model(model_path)


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
        "model_version": "catboost-v1" if model else "baseline-v1",
    }


@app.post("/predict")
def predict(features: Features) -> dict:
    if model:
        row = [
            [
                features.current_delay_min,
                features.speed,
                features.distance_to_stop_km,
                features.hour,
                features.historical_delay_min,
                features.dwell_seconds,
                features.horizon_min,
            ]
        ]
        delay = max(0.0, float(model.predict(row)[0]))
        probability = 1 / (1 + math.exp(-(delay - 3.0)))
        reason = "паттерн CatBoost"
        version = "catboost-v1"
    else:
        probability, delay, reason = heuristic(features)
        version = "baseline-v1"
    return {
        "probability": round(probability, 4),
        "predicted_delay_min": round(delay, 2),
        "reason": reason,
        "model_version": version,
    }
