from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.drone import (
    DroneClient,
    DroneMapAnalyzer,
    DroneMapAnalyzerConfig,
    DroneMapAnalyzerError,
)


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve the fictional Agent Hub drone task")
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="locate the dam without submitting mission instructions",
    )
    args = parser.parse_args()
    load_dotenv(override=True)
    hub = ApiClient(ApiConfig(
        api_url=required_environment("AGENTHUB_API_URL"),
        api_key=required_environment("AGENTHUB_API_KEY"),
        timeout_seconds=60,
    ))
    analyzer = DroneMapAnalyzer(DroneMapAnalyzerConfig(
        api_key=required_environment("OPENAI_API_KEY"),
        model=required_environment("OPENAI_MODEL"),
    ))
    drone = DroneClient(hub)
    if args.analyze_only:
        sector = analyzer.locate_dam(drone.fetch_map_data_url())
        response = {"status": "analysis only; mission not submitted"}
    else:
        sector, response = drone.solve(analyzer)
    print(f"Dam sector: column={sector.column}, row={sector.row} "
          f"(grid {sector.grid_columns}x{sector.grid_rows})")
    print(sector.explanation)
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, DroneMapAnalyzerError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"drone failed: {exc}") from exc
