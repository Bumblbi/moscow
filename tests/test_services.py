from app.schemas import MLPredictionRequest
from app.services import fallback_prediction, haversine_km, risk_level


def test_risk_thresholds():
    assert risk_level(0.39) == "low"
    assert risk_level(0.4) == "medium"
    assert risk_level(0.7) == "high"


def test_fallback_prediction_is_bounded_and_explainable():
    result = fallback_prediction(
        MLPredictionRequest(
            current_delay_min=5,
            speed=4,
            distance_to_stop_km=0.2,
            hour=8,
            historical_delay_min=3,
            dwell_seconds=180,
            horizon_min=15,
        )
    )
    assert 0 <= result.probability <= 1
    assert result.predicted_delay_min >= 5
    assert result.reason == "длительная стоянка"
    assert result.model_version == "fallback-v1"


def test_haversine_distance():
    assert haversine_km(55.7522, 37.6156, 55.7522, 37.6156) == 0
    assert 0.5 < haversine_km(55.7522, 37.6156, 55.7577, 37.6159) < 0.8
