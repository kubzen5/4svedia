from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

from dotenv import load_dotenv

from src.railway import RailwayClient, RailwayError, find_flag


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def activation_steps(help_response: Any, route: str = "X-01") -> list[dict[str, Any]]:
    """Build the shortest activation flow from the API's advertised capabilities."""

    if not isinstance(help_response, Mapping) or not isinstance(
        help_section := help_response.get("help"), Mapping
    ):
        raise RailwayError("The help response does not contain a 'help' object")
    advertised = help_section.get("actions")
    if not isinstance(advertised, list):
        raise RailwayError("The help response does not contain an actions list")

    actions: dict[str, Mapping[str, Any]] = {}
    for item in advertised:
        if isinstance(item, Mapping) and isinstance(name := item.get("action"), str):
            actions[name] = item

    expected = {
        "reconfigure": {"route"},
        "setstatus": {"route", "value"},
        "save": {"route"},
    }
    for name, required in expected.items():
        definition = actions.get(name)
        if definition is None or set(definition.get("requires", [])) != required:
            raise RailwayError(
                f"Help does not advertise the expected '{name}' parameters: {sorted(required)}"
            )

    status_values = help_section.get("status_values")
    if not isinstance(status_values, Mapping) or status_values.get("RTOPEN") != "open":
        raise RailwayError("Help does not define RTOPEN as the open route status")
    allowed = actions["setstatus"].get("allowed_values")
    if not isinstance(allowed, list) or "RTOPEN" not in allowed:
        raise RailwayError("Help does not allow RTOPEN for setstatus")

    return [
        {"action": "reconfigure", "route": route},
        {"action": "setstatus", "route": route, "value": "RTOPEN"},
        {"action": "save", "route": route},
    ]


def main() -> None:
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base_url = required_environment("AGENTHUB_API_URL").rstrip("/") + "/verify"
    client = RailwayClient(base_url, required_environment("AGENTHUB_API_KEY"))

    help_response = client.call({"action": "help"})
    print(json.dumps(help_response, ensure_ascii=False, indent=2))
    if flag := find_flag(help_response):
        print(flag)
        return

    for answer in activation_steps(help_response):
        response = client.call(answer)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        if flag := find_flag(response):
            print(flag)
            return
    raise RailwayError("The documented workflow ended without a {FLG:...} flag")


if __name__ == "__main__":
    main()
