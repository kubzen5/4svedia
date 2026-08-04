from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from src.api_client import ApiClient


SENSOR_FIELDS = {
    "temperature": ("temperature_K", 553.0, 873.0),
    "pressure": ("pressure_bar", 60.0, 160.0),
    "water": ("water_level_meters", 5.0, 15.0),
    "voltage": ("voltage_supply_v", 229.0, 231.0),
    "humidity": ("humidity_percent", 40.0, 80.0),
}


class NoteVerdict(BaseModel):
    id: int
    verdict: Literal["ok", "error", "neutral"]


class NoteVerdicts(BaseModel):
    notes: list[NoteVerdict]


class EvaluationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SensorRecord:
    file_id: str
    sensor_type: str
    values: dict[str, float]
    operator_notes: str

    @property
    def measurements_ok(self) -> bool:
        active = set(self.sensor_type.lower().split("/"))
        if not active or not active <= SENSOR_FIELDS.keys():
            return False
        for sensor, (field, minimum, maximum) in SENSOR_FIELDS.items():
            value = self.values[field]
            if sensor in active:
                if not minimum <= value <= maximum:
                    return False
            elif value != 0:
                return False
        return True


def parse_archive(payload: bytes) -> list[SensorRecord]:
    records: list[SensorRecord] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise EvaluationError("Downloaded sensor data is not a valid ZIP archive") from exc
    with archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith(".json"))
        if not names:
            raise EvaluationError("Sensor archive contains no JSON files")
        for name in names:
            try:
                data = json.loads(archive.read(name).decode("utf-8"))
                values = {field: float(data[field]) for field, _, _ in SENSOR_FIELDS.values()}
                records.append(SensorRecord(
                    file_id=Path(name).stem,
                    sensor_type=str(data["sensor_type"]).strip(),
                    values=values,
                    operator_notes=str(data["operator_notes"]).strip(),
                ))
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvaluationError(f"Invalid sensor record: {name}") from exc
    return records


class NoteClassifier:
    SYSTEM_PROMPT = """Classify each English power-plant operator note by what it CLAIMS about
the associated readings. Return 'ok' if it says readings are correct, stable, normal, safe,
within limits, or no anomaly was found. Return 'error' if it reports any fault, anomaly,
incorrect/out-of-range/suspicious reading, warning, or required investigation. Return
'neutral' only if it makes no claim about validity. Classify the claim, not the actual data.
Return exactly one verdict for every numeric id and no explanation."""

    def __init__(self, api_key: str, model: str, cache_path: Path, batch_size: int = 100) -> None:
        self.client = OpenAI(api_key=api_key, timeout=90, max_retries=3)
        self.model = model
        self.cache_path = cache_path
        self.batch_size = batch_size

    def classify(self, notes: Iterable[str]) -> dict[str, str]:
        unique = sorted(set(notes))
        cache = self._load_cache()
        missing = [note for note in unique if note not in cache]
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start:start + self.batch_size]
            payload = [{"id": index, "note": note} for index, note in enumerate(batch)]
            try:
                response = self.client.responses.parse(
                    model=self.model,
                    input=[
                        {"role": "developer", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    text_format=NoteVerdicts,
                    store=False,
                )
            except (OpenAIError, ValidationError) as exc:
                raise EvaluationError(f"Operator-note classification failed: {exc}") from exc
            parsed = response.output_parsed
            verdicts = {} if parsed is None else {item.id: item.verdict for item in parsed.notes}
            if set(verdicts) != set(range(len(batch))):
                raise EvaluationError("Model returned an incomplete operator-note classification")
            cache.update({note: verdicts[index] for index, note in enumerate(batch)})
            self._save_cache(cache)
        return {note: cache[note] for note in unique}

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluationError(f"Invalid note cache: {self.cache_path}") from exc
        return {str(key): str(value) for key, value in data.items() if value in {"ok", "error", "neutral"}}

    def _save_cache(self, cache: dict[str, str]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.cache_path)


class RuleBasedNoteClassifier:
    """Classify the finite, templated note vocabulary without data disclosure."""

    ERROR_OPENINGS = {
        "I am not comfortable with this result",
        "I am seeing an unexpected pattern",
        "I can see a clear irregularity",
        "Something is clearly off",
        "The current result seems unreliable",
        "The latest behavior is concerning",
        "The numbers feel inconsistent",
        "The output quality is doubtful",
        "The report does not look healthy",
        "The signal profile looks unusual",
        "The situation requires attention",
        "There is a visible anomaly here",
        "These readings look suspicious",
        "This check did not look right",
        "This is not the pattern I expected",
        "This report raises serious doubts",
        "This run shows questionable behavior",
        "This state looks unstable",
    }
    OK_OPENINGS = {
        "All telemetry looks steady", "Current status remains healthy",
        "Daily monitoring confirms stability", "Everything checks out",
        "Execution quality is high", "Health indicators remain strong",
        "No concerning drift is present", "No irregular behavior is visible",
        "No warning signs appeared", "Observed values stay controlled",
        "Operational state is consistent", "Performance appears nominal",
        "Readings are calm and predictable", "Routine diagnostics are positive",
        "Service condition is excellent", "System behavior is fully stable",
        "The latest report looks clean", "The operating profile stays normal",
        "The overall picture is solid", "The process stayed balanced",
        "The recent snapshot is reassuring", "The trend line is quiet",
        "This cycle looks reliable", "This run finished without surprises",
        "Tracking data remains coherent",
        "The report looks completely normal. I will go to check status of all other devices.",
    }

    def classify(self, notes: Iterable[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        unknown: set[str] = set()
        for note in set(notes):
            opening = note.split(",", 1)[0].strip()
            if opening in self.ERROR_OPENINGS:
                result[note] = "error"
            elif opening in self.OK_OPENINGS:
                result[note] = "ok"
            else:
                unknown.add(opening)
        if unknown:
            examples = "; ".join(sorted(unknown)[:5])
            raise EvaluationError(f"Unknown operator-note templates: {examples}")
        return result


class EvaluationService:
    def __init__(self, hub: ApiClient, classifier: Any) -> None:
        self.hub = hub
        self.classifier = classifier

    def download_records(self) -> list[SensorRecord]:
        return parse_archive(self.hub.request_bytes("dane/sensors.zip"))

    def find_anomalies(self, records: list[SensorRecord]) -> list[str]:
        verdicts = self.classifier.classify(record.operator_notes for record in records)
        anomalies = []
        for record in records:
            note = verdicts[record.operator_notes]
            mismatch = (note == "ok" and not record.measurements_ok) or (
                note == "error" and record.measurements_ok
            )
            if not record.measurements_ok or mismatch:
                anomalies.append(record.file_id)
        return anomalies

    def submit(self, ids: list[str]) -> Any:
        return self.hub.post_json("verify", {
            "apikey": self.hub.api_key,
            "task": "evaluation",
            "answer": {"recheck": ids},
        })
