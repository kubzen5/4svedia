from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.domatowo import DomatowoWorkflow


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rescue the survivor in Domatowo")
    parser.add_argument(
        "--reconnaissance",
        choices=("help", "map", "objects", "logs", "expenses"),
        help="Perform a read-only reconnaissance request instead of the mission",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Call the helicopter for a survivor already confirmed in current logs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(override=True)
    hub = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
            timeout_seconds=15,
        )
    )
    workflow = DomatowoWorkflow(hub)
    if args.resume:
        result = workflow.resume_from_logs()
    elif args.reconnaissance == "help":
        result = workflow.help()
    elif args.reconnaissance == "map":
        result = workflow.get_map()
    elif args.reconnaissance == "objects":
        result = workflow.call("getObjects")
    elif args.reconnaissance == "logs":
        result = workflow.call("getLogs")
    elif args.reconnaissance == "expenses":
        result = workflow.call("expenses")
    else:
        result = workflow.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, RuntimeError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"domatowo failed: {exc}") from exc
