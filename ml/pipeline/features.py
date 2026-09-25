from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


WINDOWS_MINUTES = (1, 3, 5, 10)

BASE_FEATURES = [
    "cur_dev_s",
    "horizon_s",
    "hour_sin",
    "hour_cos",
    "weekday",
    "target_lon",
    "target_lat",
    "schedule_progress",
    "prev_planned_gap_s",
    "next_planned_gap_s",
    "manual_fill",
    "last_lon",
    "last_lat",
    "last_speed",
    "last_heading",
    "telemetry_age_s",
    "distance_to_target_km",
    "heading_error_deg",
    "cur_dev_delta_5m",
    "cur_dev_delta_15m",
    "cur_dev_mean_15m",
    "cur_dev_std_15m",
]
WINDOW_FEATURES = [
    f"{name}_{window}m"
    for window in WINDOWS_MINUTES
    for name in (
        "telemetry_count",
        "valid_ratio",
        "speed_mean",
        "speed_std",
        "speed_min",
        "speed_max",
        "speed_delta",
        "stationary_ratio",
        "movement_km",
    )
]
FEATURE_COLUMNS = BASE_FEATURES + WINDOW_FEATURES


def load_split(data_dir: Path, split: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load prediction points, traffic and schedule for a dataset split."""
    data_dir = Path(data_dir)
    if split in {"train", "test"}:
        points = pd.read_csv(data_dir / "labels" / f"labels_{split}.csv")
        schedule_name = "schedule.csv"
    elif split == "validate":
        points = pd.read_csv(data_dir / split / "points.csv")
        schedule_name = "schedule_plan.csv"
    else:
        raise ValueError(f"unknown split: {split}")
    traffic = pd.read_csv(data_dir / split / "traffic.csv", low_memory=False)
    schedule = pd.read_csv(data_dir / split / schedule_name)
    return points, traffic, schedule


def _parse_point_geometry(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    extracted = series.astype(str).str.extract(
        r"POINT\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*\)", expand=True
    )
    return pd.to_numeric(extracted[0], errors="coerce"), pd.to_numeric(extracted[1], errors="coerce")


def _haversine_km(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    radius = 6371.0
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    value = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius * np.arcsin(np.sqrt(np.clip(value, 0.0, 1.0)))


def _bearing_deg(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def _schedule_features(points: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    schedule = schedule.copy()
    schedule["time_begin"] = pd.to_datetime(schedule["time_begin"], errors="coerce")
    schedule["target_lon"], schedule["target_lat"] = _parse_point_geometry(schedule["geom"])
    schedule = schedule.sort_values(["tr_id", "time_begin", "tt_action_item_id"]).reset_index(drop=True)
    grouped = schedule.groupby("tr_id", sort=False)
    schedule["schedule_index"] = grouped.cumcount()
    schedule["schedule_size"] = grouped["tt_action_item_id"].transform("size")
    schedule["schedule_progress"] = schedule["schedule_index"] / (schedule["schedule_size"] - 1).clip(lower=1)
    schedule["prev_planned_gap_s"] = grouped["time_begin"].diff().dt.total_seconds()
    schedule["next_planned_gap_s"] = -grouped["time_begin"].diff(-1).dt.total_seconds()
    selected = schedule[
        [
            "tr_id",
            "tt_action_item_id",
            "target_lon",
            "target_lat",
            "schedule_progress",
            "prev_planned_gap_s",
            "next_planned_gap_s",
            "manual_fill",
        ]
    ].drop_duplicates(["tr_id", "tt_action_item_id"], keep="last")
    return points.merge(
        selected,
        how="left",
        left_on=["tr_id", "target_stop_id"],
        right_on=["tr_id", "tt_action_item_id"],
        validate="many_to_one",
    ).drop(columns="tt_action_item_id")


def _deviation_history_features(points: pd.DataFrame) -> pd.DataFrame:
    result = points.copy()
    for column in ("cur_dev_delta_5m", "cur_dev_delta_15m", "cur_dev_mean_15m", "cur_dev_std_15m"):
        result[column] = np.nan
    for _, indices in result.groupby("tr_id", sort=False).groups.items():
        ordered = result.loc[indices].sort_values("T")
        times = ordered["T"].to_numpy(dtype="datetime64[s]").astype("int64")
        values = ordered["cur_dev_s"].to_numpy(dtype=float)
        output_indices = ordered.index.to_numpy()
        for position, timestamp in enumerate(times):
            for minutes in (5, 15):
                previous = np.searchsorted(times[: position + 1], timestamp - minutes * 60, side="right") - 1
                if previous >= 0:
                    result.loc[output_indices[position], f"cur_dev_delta_{minutes}m"] = (
                        values[position] - values[previous]
                    )
            start = np.searchsorted(times, timestamp - 15 * 60, side="left")
            history = values[start : position + 1]
            result.loc[output_indices[position], "cur_dev_mean_15m"] = float(np.mean(history))
            result.loc[output_indices[position], "cur_dev_std_15m"] = float(np.std(history))
    return result


def _movement_km(latitudes: np.ndarray, longitudes: np.ndarray) -> float:
    valid = np.isfinite(latitudes) & np.isfinite(longitudes)
    if valid.sum() < 2:
        return math.nan
    latitudes = latitudes[valid]
    longitudes = longitudes[valid]
    return float(_haversine_km(latitudes[:-1], longitudes[:-1], latitudes[1:], longitudes[1:]).sum())


def _telemetry_features(points: pd.DataFrame, traffic: pd.DataFrame) -> pd.DataFrame:
    result = points.copy()
    telemetry_columns = [
        "last_lon",
        "last_lat",
        "last_speed",
        "last_heading",
        "telemetry_age_s",
        *WINDOW_FEATURES,
    ]
    for column in telemetry_columns:
        result[column] = np.nan

    traffic = traffic.copy()
    traffic["event_time"] = pd.to_datetime(traffic["event_time"], errors="coerce")
    traffic = traffic.dropna(subset=["event_time"]).sort_values(["tr_id", "event_time"])
    traffic_groups = {key: group for key, group in traffic.groupby("tr_id", sort=False)}

    for tr_id, point_indices in result.groupby("tr_id", sort=False).groups.items():
        vehicle_traffic = traffic_groups.get(tr_id)
        if vehicle_traffic is None or vehicle_traffic.empty:
            continue
        event_times = vehicle_traffic["event_time"].to_numpy(dtype="datetime64[s]").astype("int64")
        speeds = vehicle_traffic["speed"].to_numpy(dtype=float)
        latitudes = vehicle_traffic["lat"].to_numpy(dtype=float)
        longitudes = vehicle_traffic["lon"].to_numpy(dtype=float)
        headings = vehicle_traffic["heading"].to_numpy(dtype=float)
        valid_locations = vehicle_traffic["location_valid"].fillna(False).to_numpy(dtype=bool)

        for point_index in point_indices:
            timestamp = int(result.at[point_index, "T"].timestamp())
            end = np.searchsorted(event_times, timestamp, side="right")
            if end == 0:
                continue
            prior_valid = np.flatnonzero(
                valid_locations[:end]
                & np.isfinite(latitudes[:end])
                & np.isfinite(longitudes[:end])
                & np.isfinite(speeds[:end])
            )
            if prior_valid.size:
                last = int(prior_valid[-1])
                result.loc[point_index, ["last_lon", "last_lat", "last_speed", "last_heading"]] = [
                    longitudes[last],
                    latitudes[last],
                    speeds[last],
                    headings[last],
                ]
                result.at[point_index, "telemetry_age_s"] = max(0, timestamp - event_times[last])

            for minutes in WINDOWS_MINUTES:
                start = np.searchsorted(event_times, timestamp - minutes * 60, side="left")
                window_speeds = speeds[start:end]
                window_latitudes = latitudes[start:end]
                window_longitudes = longitudes[start:end]
                window_valid = (
                    valid_locations[start:end]
                    & np.isfinite(window_speeds)
                    & np.isfinite(window_latitudes)
                    & np.isfinite(window_longitudes)
                )
                valid_speeds = window_speeds[window_valid]
                prefix = f"_{minutes}m"
                result.at[point_index, f"telemetry_count{prefix}"] = end - start
                result.at[point_index, f"valid_ratio{prefix}"] = float(window_valid.mean()) if end > start else 0.0
                if valid_speeds.size:
                    result.at[point_index, f"speed_mean{prefix}"] = float(valid_speeds.mean())
                    result.at[point_index, f"speed_std{prefix}"] = float(valid_speeds.std())
                    result.at[point_index, f"speed_min{prefix}"] = float(valid_speeds.min())
                    result.at[point_index, f"speed_max{prefix}"] = float(valid_speeds.max())
                    result.at[point_index, f"speed_delta{prefix}"] = float(valid_speeds[-1] - valid_speeds[0])
                    result.at[point_index, f"stationary_ratio{prefix}"] = float((valid_speeds < 1.0).mean())
                    result.at[point_index, f"movement_km{prefix}"] = _movement_km(
                        window_latitudes[window_valid], window_longitudes[window_valid]
                    )
    return result


def build_features(points: pd.DataFrame, traffic: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Build leakage-safe features using only telemetry observed at or before each point's T."""
    result = points.copy()
    result["T"] = pd.to_datetime(result["T"], errors="raise")
    result["target_time_begin"] = pd.to_datetime(result["target_time_begin"], errors="raise")
    result["horizon_s"] = (result["target_time_begin"] - result["T"]).dt.total_seconds()
    seconds_of_day = result["T"].dt.hour * 3600 + result["T"].dt.minute * 60 + result["T"].dt.second
    phase = 2 * np.pi * seconds_of_day / 86400.0
    result["hour_sin"] = np.sin(phase)
    result["hour_cos"] = np.cos(phase)
    result["weekday"] = result["T"].dt.dayofweek.astype(float)
    result = _schedule_features(result, schedule)
    result = _deviation_history_features(result)
    result = _telemetry_features(result, traffic)
    result["distance_to_target_km"] = _haversine_km(
        result["last_lat"].to_numpy(dtype=float),
        result["last_lon"].to_numpy(dtype=float),
        result["target_lat"].to_numpy(dtype=float),
        result["target_lon"].to_numpy(dtype=float),
    )
    bearing = _bearing_deg(
        result["last_lat"].to_numpy(dtype=float),
        result["last_lon"].to_numpy(dtype=float),
        result["target_lat"].to_numpy(dtype=float),
        result["target_lon"].to_numpy(dtype=float),
    )
    result["heading_error_deg"] = np.abs((result["last_heading"].to_numpy(dtype=float) - bearing + 180) % 360 - 180)
    result["manual_fill"] = result["manual_fill"].astype(float)
    return result


def model_matrix(features: pd.DataFrame) -> pd.DataFrame:
    """Return model features in a stable order."""
    return features.reindex(columns=FEATURE_COLUMNS).replace([np.inf, -np.inf], np.nan)
