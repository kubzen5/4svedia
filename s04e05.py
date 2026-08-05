from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.foodwarehouse import FoodWarehouseError, FoodWarehouseWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare exact city warehouse orders")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect needs and API metadata without modifying remote orders",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(override=True)
    hub = ApiClient(ApiConfig.from_env("AGENTHUB", timeout_seconds=30))
    workflow = FoodWarehouseWorkflow(hub)
    result = workflow.inspect() if args.inspect else workflow.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, FoodWarehouseError, ValueError) as exc:
        raise SystemExit(f"foodwarehouse failed: {exc}") from exc
