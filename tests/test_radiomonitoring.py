import base64
import gzip
import io
import zipfile

from src.radiomonitoring import attachment_text, extract_report


def test_extract_report_and_round_half_up() -> None:
    report = extract_report(
        [
            "Syjon to Nowe Miasto",
            '{"cityArea": "12.345", "warehousesCount": 321}',
            "Numer kontaktowy: +48 123-456-789",
        ]
    )
    assert report.answer() == {
        "action": "transmit",
        "cityName": "Nowe Miasto",
        "cityArea": "12.35",
        "warehousesCount": 321,
        "phoneNumber": "48123456789",
    }


def test_attachment_text_handles_gzip_and_zip() -> None:
    raw = "Syjon to Testowo".encode()
    assert attachment_text(base64.b64encode(gzip.compress(raw)).decode(), "application/gzip") == [
        "Syjon to Testowo"
    ]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("data.json", '{"cityArea": 1.2}')
    assert attachment_text(base64.b64encode(stream.getvalue()).decode(), "application/zip") == [
        '{"cityArea": 1.2}'
    ]


def test_infers_zion_from_trade_overlap_and_existing_warehouses() -> None:
    report = extract_report(
        [
            '[{"name":"Skarszewy","occupiedArea":10.7284},'
            '{"name":"Inne","occupiedArea":3.2}]',
            "miasto,akcja,towar\nSyjon,szuka,kilof\nSyjon,sprzedaje,bydło\n"
            "Skarszewy,szuka,kilof\nSkarszewy,sprzedaje,wołowina\n"
            "Inne,szuka,kilof",
            "Planujemy na wiosnę wybudować 12 magazyn.",
            "Kontakt: 644-122-092",
        ]
    )
    assert report.answer() == {
        "action": "transmit",
        "cityName": "Skarszewy",
        "cityArea": "10.73",
        "warehousesCount": 11,
        "phoneNumber": "644122092",
    }
