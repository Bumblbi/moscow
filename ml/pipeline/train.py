from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .features import FEATURE_COLUMNS, build_features, load_split, model_matrix


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def make_model(iterations: int, random_seed: int):
    try:
        from catboost import CatBoostRegressor
    except ImportError as error:
        raise RuntimeError("CatBoost is required. Install ml/requirements.txt first.") from error
    return CatBoostRegressor(
        loss_function="MAE",
        eval_metric="MAE",
        iterations=iterations,
        depth=6,
        learning_rate=0.035,
        l2_leaf_reg=8.0,
        random_seed=random_seed,
        random_strength=0.4,
        bootstrap_type="Bayesian",
        bagging_temperature=0.4,
        allow_writing_files=False,
        verbose=100,
    )


def train_and_evaluate(data_dir: Path, model_dir: Path, iterations: int, random_seed: int) -> dict:
    train_points, train_traffic, train_schedule = load_split(data_dir, "train")
    test_points, test_traffic, test_schedule = load_split(data_dir, "test")
    train_features = build_features(train_points, train_traffic, train_schedule)
    test_features = build_features(test_points, test_traffic, test_schedule)

    x_train = model_matrix(train_features)
    y_train = train_features["target_delay_s"].to_numpy(dtype=float)
    x_test = model_matrix(test_features)
    y_test = test_features["target_delay_s"].to_numpy(dtype=float)

    model = make_model(iterations, random_seed)
    model.fit(x_train, y_train, eval_set=(x_test, y_test), early_stopping_rounds=100, verbose=100)
    prediction = model.predict(x_test)
    metrics = {
        "train_rows": int(len(x_train)),
        "test_rows": int(len(x_test)),
        "mae_model_s": mae(y_test, prediction),
        "mae_cur_dev_s": mae(y_test, test_features["cur_dev_s"].to_numpy(dtype=float)),
        "mae_zero_s": mae(y_test, np.zeros_like(y_test)),
        "best_iteration": int(model.get_best_iteration()),
    }

    model_dir.mkdir(parents=True, exist_ok=True)
    evaluation_model_path = model_dir / "delay_model_evaluation.cbm"
    model.save_model(evaluation_model_path)
    (model_dir / "evaluation_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metrics


def fit_final_model(
    data_dir: Path,
    model_dir: Path,
    iterations: int,
    random_seed: int,
    submission_path: Path | None,
) -> dict:
    train_points, train_traffic, train_schedule = load_split(data_dir, "train")
    test_points, test_traffic, test_schedule = load_split(data_dir, "test")
    train_features = build_features(train_points, train_traffic, train_schedule)
    test_features = build_features(test_points, test_traffic, test_schedule)
    combined_features = pd.concat([train_features, test_features], ignore_index=True)

    model = make_model(iterations, random_seed)
    model.fit(
        model_matrix(combined_features),
        combined_features["target_delay_s"].to_numpy(dtype=float),
        verbose=100,
    )
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / "competition_delay_model.cbm"
    model.save_model(model_path)
    metadata = {
        "model_version": "catboost-telemetry-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "feature_columns": FEATURE_COLUMNS,
        "target": "target_delay_s",
        "target_unit": "seconds",
        "training_rows": int(len(combined_features)),
        "iterations": iterations,
        "random_seed": random_seed,
    }
    (model_dir / "competition_delay_model.metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if submission_path is not None:
        from .submission import create_submission

        create_submission(data_dir, model_path, submission_path)
    return metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and evaluate the transport-delay CatBoost model")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("ml/models"))
    parser.add_argument("--iterations", type=int, default=900)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-final", action="store_true")
    parser.add_argument("--submission", type=Path, default=Path("ml/outputs/submission.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = train_and_evaluate(args.data_dir, args.model_dir, args.iterations, args.seed)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if not args.skip_final:
        final_iterations = max(100, metrics["best_iteration"] + 1)
        metadata = fit_final_model(
            args.data_dir,
            args.model_dir,
            final_iterations,
            args.seed,
            args.submission,
        )
        print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
