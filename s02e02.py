from __future__ import annotations

import os
import argparse

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.electricity import ElectricityClient


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve the Agent Hub electricity puzzle")
    parser.add_argument("--reset", action="store_true", help="reset the board before solving")
    args = parser.parse_args()
    load_dotenv(override=True)
    client = ApiClient(ApiConfig(api_url=required_environment("AGENTHUB_API_URL"), api_key=required_environment("AGENTHUB_API_KEY")))
    print(ElectricityClient(client).solve(reset=args.reset))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"electricity failed: {exc}") from exc
