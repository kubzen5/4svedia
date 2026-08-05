from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.api_client import ApiClient, ApiClientError, ApiConfig
from src.evaluation import (
    EvaluationError, EvaluationService, NoteClassifier, RuleBasedNoteClassifier,
    parse_archive,
)


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing {name}; configure it using .env-example")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Find and submit anomalous sensor records")
    parser.add_argument("--analyze-only", action="store_true", help="do not submit to /verify")
    parser.add_argument("--use-openai", action="store_true", help="classify notes with OpenAI")
    args = parser.parse_args()
    load_dotenv(override=True)

    hub = ApiClient(ApiConfig(
        api_url=required_environment("AGENTHUB_API_URL"),
        api_key=required_environment("AGENTHUB_API_KEY"),
        timeout_seconds=90,
    ))
    classifier = (NoteClassifier(
        api_key=required_environment("OPENAI_API_KEY"),
        model=required_environment("OPENAI_MODEL"),
        cache_path=Path(".cache/evaluation_notes.json"),
    ) if args.use_openai else RuleBasedNoteClassifier())
    service = EvaluationService(hub, classifier)
    cached_archive = Path(".cache/sensors.zip")
    records = (parse_archive(cached_archive.read_bytes()) if cached_archive.exists()
               else service.download_records())
    unique_notes = len({record.operator_notes for record in records})
    anomalies = service.find_anomalies(records)
    print(f"Records: {len(records)}; unique notes: {unique_notes}; anomalies: {len(anomalies)}")
    print(json.dumps({"recheck": anomalies}, ensure_ascii=False))
    if not args.analyze_only:
        print(json.dumps(service.submit(anomalies), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ApiClientError, EvaluationError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"evaluation failed: {exc}") from exc
