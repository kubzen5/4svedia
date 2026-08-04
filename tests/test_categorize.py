from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src.api_client import ApiClient, ApiConfig
from src.categorize import CargoItem, PROMPTS, build_prompt, parse_items


def csv_payload(rows: int = 10) -> bytes:
    body = "id,description\n" + "".join(
        f"item-{number},ordinary item {number}\n" for number in range(rows)
    )
    return body.encode()


class CategorizeTests(unittest.TestCase):
    def test_parse_items_requires_exactly_ten_unique_rows(self) -> None:
        items = parse_items(csv_payload())
        self.assertEqual(len(items), 10)
        self.assertEqual(items[0], CargoItem("item-0", "ordinary item 0"))

    def test_parse_items_rejects_wrong_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected 10"):
            parse_items(csv_payload(9))

    def test_parse_items_accepts_semicolon_and_alternative_headers(self) -> None:
        payload = (
            "code;content\n"
            + "".join(f"C-{number};cargo {number}\n" for number in range(10))
        ).encode()
        items = parse_items(payload)
        self.assertEqual(items[0], CargoItem("C-0", "cargo 0"))

    def test_prompt_marks_reactor_cargo_as_neutral(self) -> None:
        prompt = build_prompt(CargoItem("RX-1", "reactor cassette"))
        self.assertIn("Reactor=NEU always", prompt)
        self.assertIn("RX-1: reactor cassette", prompt)

    def test_all_prompt_variants_replace_placeholders(self) -> None:
        item = CargoItem("X-1", "safe part")
        for template in PROMPTS:
            prompt = build_prompt(item, template)
            self.assertNotIn("{id}", prompt)
            self.assertNotIn("{description}", prompt)

    def test_client_can_decode_hub_error_response_when_requested(self) -> None:
        body = json.dumps({"code": -890, "message": "NOT ACCEPTED"}).encode()
        error = HTTPError("https://example.test/verify", 406, "", {}, None)
        error.read = lambda: body  # type: ignore[method-assign]
        client = ApiClient(ApiConfig("https://example.test", "secret"))

        with patch("src.api_client.urlopen", side_effect=error):
            response = client.post_json(
                "verify", {}, allow_http_error_response=True
            )

        self.assertEqual(response["code"], -890)


if __name__ == "__main__":
    unittest.main()
