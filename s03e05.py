from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.savethem import MissionTools, SaveThemError, plan_route, verify


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan and submit the Skolwin route")
    parser.add_argument("--plan-only", action="store_true", help="do not submit to /verify")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(override=True)
    hub = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
            timeout_seconds=30,
        )
    )
    grid, vehicles = MissionTools(hub).load_mission("Skolwin")
    route = plan_route(grid, vehicles)
    print(json.dumps({
        "answer": route.answer,
        "fuel_used": route.fuel_used / 10,
        "food_used": route.food_used / 10,
    }, ensure_ascii=False, indent=2))
    if not args.plan_only:
        print(json.dumps(verify(hub, route), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, SaveThemError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"savethem failed: {exc}") from exc
