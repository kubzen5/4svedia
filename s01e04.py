from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiConfig
from src.sendit import build_sendit_declaration


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    load_dotenv(override=True)
    client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    declaration = build_sendit_declaration().render()
    print(declaration)
    result = client.post_json(
        "verify",
        {
            "apikey": client.api_key,
            "task": "sendit",
            "answer": {"declaration": declaration},
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
