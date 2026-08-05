from __future__ import annotations

import base64
import csv
import gzip
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping

from src.api_client import ApiClient, ApiClientError


TASK_NAME = "radiomonitoring"
MAX_LISTEN_CALLS = 500
MAX_ATTACHMENT_BYTES = 50_000_000


class RadioMonitoringError(RuntimeError):
    """Raised when captured material cannot produce a complete report."""


@dataclass(frozen=True, slots=True)
class CityReport:
    city_name: str
    city_area: str
    warehouses_count: int
    phone_number: str

    def answer(self) -> dict[str, str | int]:
        return {
            "action": "transmit",
            "cityName": self.city_name,
            "cityArea": self.city_area,
            "warehousesCount": self.warehouses_count,
            "phoneNumber": self.phone_number,
        }


def _verify(hub: ApiClient, answer: Mapping[str, Any]) -> Mapping[str, Any]:
    response = hub.post_json(
        "verify", {"apikey": hub.api_key, "task": TASK_NAME, "answer": answer}
    )
    if not isinstance(response, Mapping):
        raise ApiClientError("radiomonitoring returned a non-object response")
    return response


def _decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-16", "cp1250"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        printable = sum(character.isprintable() or character.isspace() for character in text)
        if text and printable / len(text) >= 0.85:
            return text
    return None


def attachment_text(attachment: str, media_type: str = "") -> list[str]:
    """Decode an attachment locally and return only useful textual payloads."""

    try:
        data = base64.b64decode(attachment, validate=True)
    except (ValueError, TypeError) as exc:
        raise RadioMonitoringError("attachment is not valid Base64") from exc
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise RadioMonitoringError("decoded attachment exceeds the 50 MB safety limit")

    if data.startswith(b"\x1f\x8b") or "gzip" in media_type.lower():
        try:
            data = gzip.decompress(data)
        except (OSError, EOFError) as exc:
            raise RadioMonitoringError("invalid gzip attachment") from exc

    normalized_media_type = media_type.lower().split(";", 1)[0].strip()
    if data.startswith(b"PK\x03\x04") or normalized_media_type in {
        "application/zip",
        "application/x-zip-compressed",
    }:
        texts: list[str] = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if info.is_dir() or info.file_size > MAX_ATTACHMENT_BYTES:
                        continue
                    value = _decode_text(archive.read(info))
                    if value:
                        texts.append(value)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise RadioMonitoringError("invalid ZIP attachment") from exc
        return texts

    if normalized_media_type.startswith("image/"):
        from rapidocr_onnxruntime import RapidOCR

        result, _ = RapidOCR()(data)
        return ["\n".join(item[1] for item in result)] if result else []

    if normalized_media_type.startswith("audio/"):
        from faster_whisper import WhisperModel

        suffix = ".mp3" if normalized_media_type == "audio/mpeg" else ".audio"
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
                audio_file.write(data)
                temporary_path = audio_file.name
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(
                temporary_path, language="pl", beam_size=5
            )
            transcription = " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            )
            return [transcription] if transcription else []
        finally:
            if temporary_path:
                import os

                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    text = _decode_text(data)
    return [text] if text else []


def collect_materials(hub: ApiClient) -> list[str]:
    """Start a fresh session and collect all useful text until the API says to stop."""

    _verify(hub, {"action": "start"})
    materials: list[str] = []
    for _ in range(MAX_LISTEN_CALLS):
        response = _verify(hub, {"action": "listen"})
        transcription = response.get("transcription")
        if isinstance(transcription, str) and transcription.strip():
            materials.append(transcription.strip())
        attachment = response.get("attachment")
        if isinstance(attachment, str) and attachment:
            media_type = response.get("meta")
            materials.extend(
                attachment_text(attachment, media_type if isinstance(media_type, str) else "")
            )
        message = str(response.get("message", "")).lower()
        if response.get("code") != 100 or any(
            marker in message
            for marker in ("enough", "wystarcz", "finished", "complete", "koniec")
        ):
            return materials
    raise RadioMonitoringError(f"listen limit ({MAX_LISTEN_CALLS}) exceeded")


def _flatten_json(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from _flatten_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _flatten_json(nested)
    elif value is not None:
        yield str(value)


def _normalized_corpus(materials: Iterable[str]) -> str:
    chunks: list[str] = []
    for material in materials:
        try:
            parsed = json.loads(material)
        except json.JSONDecodeError:
            chunks.append(material)
        else:
            chunks.append("\n".join(_flatten_json(parsed)))
        # CSV values remain easy to search, while this also normalizes separators.
        try:
            rows = csv.reader(io.StringIO(material))
            chunks.extend(" ".join(row) for row in rows)
        except csv.Error:
            pass
    return "\n".join(chunks)


def _last_match(patterns: Iterable[str], text: str, field: str) -> str:
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    if not matches:
        raise RadioMonitoringError(f"could not determine {field}")
    return matches[-1].strip(" \t\r\n.,;:")


def _trade_item(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"bydło", "wołowina", "krowa", "mięso"}:
        return "cattle"
    return normalized


def _structured_city_data(
    materials: Iterable[str],
) -> tuple[dict[str, Decimal], dict[str, set[tuple[str, str]]]]:
    areas: dict[str, Decimal] = {}
    trades: dict[str, set[tuple[str, str]]] = {}
    for material in materials:
        try:
            value = json.loads(material)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, list):
            for record in value:
                if not isinstance(record, Mapping):
                    continue
                name, area = record.get("name"), record.get("occupiedArea")
                if isinstance(name, str) and isinstance(area, (int, float, str)):
                    try:
                        areas[name] = Decimal(str(area))
                    except InvalidOperation:
                        pass

        try:
            rows = csv.DictReader(io.StringIO(material))
            if not rows.fieldnames or not {"miasto", "akcja", "towar"}.issubset(
                rows.fieldnames
            ):
                continue
            for row in rows:
                city, action, item = row.get("miasto"), row.get("akcja"), row.get("towar")
                if city and action and item:
                    trades.setdefault(city.strip(), set()).add(
                        (action.strip().lower(), _trade_item(item))
                    )
        except csv.Error:
            continue
    return areas, trades


def _infer_city_and_area(materials: list[str]) -> tuple[str, str]:
    areas, trades = _structured_city_data(materials)
    zion = trades.get("Syjon", set())
    candidates: list[tuple[int, str]] = []
    for city, city_trades in trades.items():
        if city != "Syjon" and city in areas:
            candidates.append((len(zion & city_trades), city))
    if not candidates:
        raise RadioMonitoringError("could not correlate Syjon with a known city")
    candidates.sort(reverse=True)
    if candidates[0][0] < 2 or (
        len(candidates) > 1 and candidates[0][0] == candidates[1][0]
    ):
        raise RadioMonitoringError("Syjon trade correlation is ambiguous")
    city = candidates[0][1]
    area = areas[city].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return city, format(area, ".2f")


def extract_report(materials: Iterable[str]) -> CityReport:
    material_list = list(materials)
    text = _normalized_corpus(material_list)
    try:
        city_name, city_area = _infer_city_and_area(material_list)
    except RadioMonitoringError:
        city_name = _last_match(
            (
                r"(?:Syjon(?:em)?\s+(?:jest|to)|miasto\s+(?:zwane|nazywane)\s+Syjonem)\s*[:=-]?\s*([A-ZĄĆĘŁŃÓŚŹŻ][\wĄĆĘŁŃÓŚŹŻąćęłńóśźż -]{1,50})",
                r'"cityName"\s*:\s*"([^"]+)"',
            ),
            text,
            "cityName",
        )
        area_raw = _last_match(
            (
                r'(?:powierzchni\w*|area|cityArea)\s*[:=-]?\s*["\']?([0-9]+(?:[.,][0-9]+)?)',
                r'([0-9]+(?:[.,][0-9]+)?)\s*(?:km(?:²|2)|kilometr\w*\s+kwadratow\w*)',
            ),
            text,
            "cityArea",
        )
        try:
            area = Decimal(area_raw.replace(",", ".")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except InvalidOperation as exc:
            raise RadioMonitoringError("cityArea is not numeric") from exc
        city_area = format(area, ".2f")

    planned_warehouse = re.findall(
        r"(?:wybudować|zbudować|postawić)\s+(\d+)\.?\s*magazyn",
        text,
        flags=re.IGNORECASE,
    )
    warehouses_raw = _last_match(
        (
            r'(?:magazyn\w*|warehousesCount)\s*[:=-]?\s*["\']?([0-9]+)',
            r'([0-9]+)\s+magazyn\w*',
        ),
        text,
        "warehousesCount",
    )
    phone = _last_match(
        (
            r'(?<!\d)(\d{3}[ -]\d{3}[ -]\d{3})(?!\d)',
            r'(?:telefon\w*|phoneNumber|numer\s+kontaktow\w*)\s*[:=-]?\s*["\']?(\+?[0-9][0-9 ()-]{6,20})',
        ),
        text,
        "phoneNumber",
    )
    digits = re.sub(r"\D", "", phone)
    if not 7 <= len(digits) <= 15:
        raise RadioMonitoringError("phoneNumber has an invalid length")
    warehouses = int(planned_warehouse[-1]) - 1 if planned_warehouse else int(warehouses_raw)
    if warehouses < 0:
        raise RadioMonitoringError("warehousesCount cannot be negative")
    return CityReport(city_name, city_area, warehouses, digits)


class RadioMonitoringWorkflow:
    def __init__(self, hub: ApiClient) -> None:
        self.hub = hub

    def run(self) -> Mapping[str, Any]:
        materials = collect_materials(self.hub)
        report = extract_report(materials)
        return _verify(self.hub, report.answer())
