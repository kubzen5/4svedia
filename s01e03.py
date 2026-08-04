from __future__ import annotations

import os
from http.server import ThreadingHTTPServer

from dotenv import load_dotenv
from openai import OpenAI

from src.api_client import ApiClient, ApiConfig
from src.logistics_proxy import LogisticsAssistant, PackageService, make_handler


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it in .env")
    return value


def main() -> None:
    load_dotenv(override=True)
    host = os.getenv("PROXY_HOST", "127.0.0.1")
    port = int(os.getenv("PROXY_PORT", "3000"))

    package_client = ApiClient(
        ApiConfig(
            api_url=required_environment("AGENTHUB_API_URL"),
            api_key=required_environment("AGENTHUB_API_KEY"),
        )
    )
    openai = OpenAI(api_key=required_environment("OPENAI_API_KEY"))
    assistant = LogisticsAssistant(
        completions=openai.chat.completions,
        model=required_environment("OPENAI_MODEL"),
        packages=PackageService(package_client),
    )
    server = ThreadingHTTPServer((host, port), make_handler(assistant))
    print(f"Logistics proxy listening on http://{host}:{port}/assistant")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
