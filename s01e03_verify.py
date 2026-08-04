from __future__ import annotations

import json
import os
import secrets
from typing import Any
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiConfig


NGROK_TUNNELS_URL = "http://127.0.0.1:4040/api/tunnels"


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it in .env")
    return value


def get_json(url: str, timeout: float = 10.0) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            # Free ngrok endpoints show an HTML interstitial to browser-like clients.
            "ngrok-skip-browser-warning": "s01e03",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"Cannot connect to {url}: {exc.reason}") from exc


def discover_public_url() -> str:
    configured = os.getenv("PROXY_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    payload = get_json(NGROK_TUNNELS_URL)
    tunnels = payload.get("tunnels", []) if isinstance(payload, dict) else []
    urls = [
        tunnel.get("public_url", "")
        for tunnel in tunnels
        if isinstance(tunnel, dict)
        and str(tunnel.get("public_url", "")).startswith("https://")
    ]
    if not urls:
        raise RuntimeError("No active HTTPS ngrok tunnel found on port 4040")
    return urls[0].rstrip("/") + "/assistant"


def health_url(endpoint_url: str) -> str:
    base = endpoint_url.removesuffix("/assistant").rstrip("/") + "/"
    return urljoin(base, "health")


def main() -> None:
    load_dotenv(override=True)
    endpoint = discover_public_url()
    health = get_json(health_url(endpoint))
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RuntimeError(f"Public health check failed: {health!r}")

    client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    print(f"Submitting public endpoint: {endpoint}")
    session_id = secrets.token_urlsafe(12)
    result = client.post_json(
        "verify",
        {
            "apikey": client.api_key,
            "task": "proxy",
            "answer": {"url": endpoint, "sessionID": session_id},
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
