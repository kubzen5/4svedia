from __future__ import annotations
from dotenv import load_dotenv
load_dotenv(override=True)
import os

from src.api_client import ApiClient, ApiConfig, ApiClientError
from src.categorize import run_classification


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    flag = run_classification(client)
    if flag:
        print(flag)


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"categorize failed: {exc}") from exc
