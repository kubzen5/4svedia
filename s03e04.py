from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urljoin

from dotenv import load_dotenv

from s01e03_verify import discover_public_url, get_json
from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.negotiations import NegotiationsError, ProductIndex, make_handler


TASK = "negotiations"
TOOL_DESCRIPTION = (
    "Podaj w params naturalny, precyzyjny opis JEDNEGO produktu wraz z jego "
    "parametrami, np. mocą lub napięciem. Wywołaj osobno dla każdego z 3 "
    "przedmiotów. Odpowiedź zawiera oferujące go miasta; wynikiem są wyłącznie "
    "miasta obecne na wszystkich 3 listach."
)


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and register the negotiations tool")
    parser.add_argument("--serve-only", action="store_true", help="start the local API without verification")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--max-wait-seconds", type=float, default=120.0)
    return parser.parse_args()


def endpoint_from_tunnel() -> str:
    configured = os.getenv("NEGOTIATIONS_PUBLIC_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    discovered = discover_public_url()
    base = discovered.removesuffix("/assistant").rstrip("/")
    return f"{base}/search"


def main() -> None:
    args = parse_args()
    load_dotenv(override=True)
    host = os.getenv("NEGOTIATIONS_HOST", "127.0.0.1")
    port = int(os.getenv("NEGOTIATIONS_PORT", "3000"))
    hub = ApiClient(ApiConfig(
        api_url=required_environment("AGENTHUB_API_URL"),
        api_key=required_environment("AGENTHUB_API_KEY"),
        timeout_seconds=30,
    ))

    print("Downloading and indexing product availability...")
    index = ProductIndex.download(hub)
    server = ThreadingHTTPServer((host, port), make_handler(index))
    if args.serve_only:
        print(f"Negotiations tool listening on http://{host}:{port}/search")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = endpoint_from_tunnel()
        health = get_json(urljoin(endpoint.rstrip("/") + "/", "../health"))
        if not isinstance(health, dict) or health.get("status") != "ok":
            raise RuntimeError(f"Public health check failed: {health!r}")
        print(f"Submitting tool: {endpoint}")
        submitted = hub.post_json("verify", {
            "apikey": hub.api_key,
            "task": TASK,
            "answer": {"tools": [{"URL": endpoint, "description": TOOL_DESCRIPTION}]},
        })
        print(json.dumps(submitted, ensure_ascii=False, indent=2))

        deadline = time.monotonic() + args.max_wait_seconds
        while time.monotonic() < deadline:
            time.sleep(args.poll_seconds)
            result = hub.post_json("verify", {
                "apikey": hub.api_key,
                "task": TASK,
                "answer": {"action": "check"},
            })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            serialized = json.dumps(result, ensure_ascii=False)
            if "FLG:" in serialized:
                return
        raise RuntimeError("Verification did not finish before the configured timeout")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, NegotiationsError, RuntimeError, ValueError, OSError) as exc:
        raise SystemExit(f"negotiations failed: {exc}") from exc
