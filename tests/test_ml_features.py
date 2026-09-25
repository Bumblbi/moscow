from datetime import datetime

import pandas as pd

from ml.pipeline.features import build_features, model_matrix


def test_features_never_use_future_telemetry():
    points = pd.DataFrame(
        {
            "sample_id": ["1"],
            "tr_id": [10],
            "T": ["2026-01-06 10:00:00"],
            "target_stop_id": [100],
            "target_time_begin": ["2026-01-06 10:12:00"],
            "cur_dev_s": [30.0],
        }
    )
    traffic = pd.DataFrame(
        {
            "tr_id": [10, 10, 10],
            "event_time": [
                "2026-01-06 09:58:00",
                "2026-01-06 10:00:00",
                "2026-01-06 10:00:01",
            ],
            "location_valid": [True, True, True],
            "lon": [37.60, 37.61, 37.99],
            "lat": [55.70, 55.71, 55.99],
            "speed": [10.0, 20.0, 200.0],
            "heading": [0.0, 90.0, 180.0],
        }
    )
    schedule = pd.DataFrame(
        {
            "tt_action_item_id": [100],
            "time_begin": ["2026-01-06 10:12:00"],
            "tr_id": [10],
            "geom": ["POINT (37.62 55.72)"],
            "manual_fill": [False],
        }
    )

    features = build_features(points, traffic, schedule)

    assert features.loc[0, "last_speed"] == 20.0
    assert features.loc[0, "last_heading"] == 90.0
    assert features.loc[0, "telemetry_age_s"] == 0.0
    assert features.loc[0, "speed_max_3m"] == 20.0
    assert features.loc[0, "horizon_s"] == 720.0
    assert model_matrix(features).shape[0] == 1


def test_deviation_history_uses_only_current_and_earlier_points():
    points = pd.DataFrame(
        {
            "sample_id": ["1", "2", "3"],
            "tr_id": [10, 10, 10],
            "T": [
                "2026-01-06 10:00:00",
                "2026-01-06 10:05:00",
                "2026-01-06 10:10:00",
            ],
            "target_stop_id": [100, 100, 100],
            "target_time_begin": [
                "2026-01-06 10:12:00",
                "2026-01-06 10:17:00",
                "2026-01-06 10:22:00",
            ],
            "cur_dev_s": [10.0, 30.0, 90.0],
        }
    )
    traffic = pd.DataFrame(
        {
            "tr_id": [10],
            "event_time": [datetime(2026, 1, 6, 10, 0)],
            "location_valid": [True],
            "lon": [37.61],
            "lat": [55.71],
            "speed": [20.0],
            "heading": [90.0],
        }
    )
    schedule = pd.DataFrame(
        {
            "tt_action_item_id": [100],
            "time_begin": ["2026-01-06 10:12:00"],
            "tr_id": [10],
            "geom": ["POINT (37.62 55.72)"],
            "manual_fill": [False],
        }
    )

    features = build_features(points, traffic, schedule)

    assert pd.isna(features.loc[0, "cur_dev_delta_5m"])
    assert features.loc[1, "cur_dev_delta_5m"] == 20.0
    assert features.loc[2, "cur_dev_delta_5m"] == 60.0
    assert features.loc[1, "cur_dev_mean_15m"] == 20.0
