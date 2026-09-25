from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .features import build_features, load_split, model_matrix


def create_submission(data_dir: Path, model_path: Path, output_path: Path) -> Path:
    try:
        from catboost import CatBoostRegressor
    except ImportError as error:
        raise RuntimeError("CatBoost is required. Install ml/requirements.txt first.") from error

    points, traffic, schedule = load_split(data_dir, "validate")
    features = build_features(points, traffic, schedule)
    model = CatBoostRegressor()
    model.load_model(model_path)
    predictions = model.predict(model_matrix(features))
    predicted = pd.DataFrame({"sample_id": features["sample_id"], "prediction": predictions})

    template = pd.read_csv(Path(data_dir) / "sample_submission.csv", sep=";")
    if not template["sample_id"].is_unique:
        raise ValueError("sample_submission.csv contains duplicate sample_id values")
    submission = template[["sample_id"]].merge(predicted, on="sample_id", how="left", validate="one_to_one")
    if submission["prediction"].isna().any():
        missing = submission.loc[submission["prediction"].isna(), "sample_id"].tolist()
        raise ValueError(f"missing predictions for {len(missing)} samples")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    submission.to_csv(output_path, sep=";", index=False, encoding="utf-8", float_format="%.6f")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a validate submission from a trained model")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=Path("ml/models/competition_delay_model.cbm"))
    parser.add_argument("--output", type=Path, default=Path("ml/outputs/submission.csv"))
    args = parser.parse_args()
    print(create_submission(args.data_dir, args.model, args.output))


if __name__ == "__main__":
    main()
