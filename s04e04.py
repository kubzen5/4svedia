from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.filesystem import FilesystemError, FilesystemWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Natan's trade filesystem")
    parser.add_argument(
        "--api-help", action="store_true",
        help="Print the filesystem API contract without modifying remote state",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(override=True)
    hub = ApiClient(ApiConfig.from_env("AGENTHUB", timeout_seconds=30))
    workflow = FilesystemWorkflow(hub)
    result = workflow.help() if args.api_help else workflow.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, FilesystemError, ValueError) as exc:
        raise SystemExit(f"filesystem failed: {exc}") from exc
