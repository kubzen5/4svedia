from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.okoeditor import apply_updates


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    load_dotenv(override=True)
    hub = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
            timeout_seconds=30,
        )
    )
    responses = apply_updates(hub)
    print(json.dumps(responses, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"okoeditor failed: {exc}") from exc
