from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.windpower import WindpowerWorkflow


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    load_dotenv(override=True)
    hub = ApiClient(ApiConfig(
        api_url=required_environment("AGENTHUB_API_URL"),
        api_key=required_environment("AGENTHUB_API_KEY"),
        timeout_seconds=10,
    ))
    result = WindpowerWorkflow(hub).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, RuntimeError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"windpower failed: {exc}") from exc
