from __future__ import annotations

import json

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.phonecall import PhoneCallAudioCodec, PhoneCallError, PhoneCallWorkflow


def main() -> None:
    load_dotenv(override=True)
    hub = ApiClient(ApiConfig.from_env("AGENTHUB", timeout_seconds=60))
    codec = PhoneCallAudioCodec()
    result = PhoneCallWorkflow(hub, codec).run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, PhoneCallError, ValueError) as exc:
        raise SystemExit(f"phonecall failed: {exc}") from exc
