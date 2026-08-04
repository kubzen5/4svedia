import io
import json
import zipfile

from src.evaluation import RuleBasedNoteClassifier, parse_archive


def archive(record: dict) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        zipped.writestr("0001.json", json.dumps(record))
    return output.getvalue()


def test_active_fields_in_range_and_inactive_fields_zero_are_valid() -> None:
    records = parse_archive(archive({
        "sensor_type": "temperature/voltage", "temperature_K": 553,
        "pressure_bar": 0, "water_level_meters": 0, "voltage_supply_v": 231,
        "humidity_percent": 0, "operator_notes": "Everything is fine."
    }))
    assert records[0].measurements_ok


def test_nonzero_inactive_field_is_anomaly() -> None:
    records = parse_archive(archive({
        "sensor_type": "water", "temperature_K": 0, "pressure_bar": 0,
        "water_level_meters": 10, "voltage_supply_v": 230,
        "humidity_percent": 0, "operator_notes": "Everything is fine."
    }))
    assert not records[0].measurements_ok


def test_rule_based_note_classifier_handles_both_claims() -> None:
    notes = [
        "Everything checks out, all values follow expected distribution.",
        "These readings look suspicious, this result is outside expected behavior.",
    ]
    assert RuleBasedNoteClassifier().classify(notes) == {
        notes[0]: "ok", notes[1]: "error",
    }
