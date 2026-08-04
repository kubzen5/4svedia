import json
import unittest

from s01e05 import activation_steps
from src.railway import HttpResponse, RailwayClient, find_flag, retry_delay


class RailwayTests(unittest.TestCase):
    def test_builds_activation_steps_from_advertised_help(self) -> None:
        help_response = {
            "ok": True,
            "help": {
                "actions": [
                    {"action": "help", "requires": []},
                    {"action": "reconfigure", "requires": ["route"]},
                    {"action": "getstatus", "requires": ["route"]},
                    {
                        "action": "setstatus",
                        "requires": ["route", "value"],
                        "allowed_values": ["RTOPEN", "RTCLOSE"],
                    },
                    {"action": "save", "requires": ["route"]},
                ],
                "status_values": {"RTOPEN": "open", "RTCLOSE": "close"},
            },
        }

        self.assertEqual(
            activation_steps(help_response),
            [
                {"action": "reconfigure", "route": "X-01"},
                {"action": "setstatus", "route": "X-01", "value": "RTOPEN"},
                {"action": "save", "route": "X-01"},
            ],
        )

    def test_retries_503_using_retry_after(self) -> None:
        responses = iter(
            [
                HttpResponse(503, {"Retry-After": "3"}, b'{"error":"busy"}'),
                HttpResponse(200, {}, b'{"ok":true}'),
            ]
        )
        sleeps: list[float] = []
        client = RailwayClient(
            "https://example.test/verify",
            "secret",
            transport=lambda request, timeout: next(responses),
            sleep=sleeps.append,
        )

        self.assertEqual(client.call({"action": "help"}), {"ok": True})
        self.assertEqual(sleeps, [3.0])

    def test_waits_when_success_consumes_rate_limit(self) -> None:
        client = RailwayClient(
            "https://example.test/verify",
            "secret",
            transport=lambda request, timeout: HttpResponse(
                200,
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "8"},
                json.dumps({"ok": True}).encode(),
            ),
            sleep=(sleeps := []).append,
        )
        client.call({"action": "help"})
        self.assertEqual(sleeps, [8.0])

    def test_finds_nested_flag(self) -> None:
        self.assertEqual(find_flag({"result": ["done {FLG:railway}"]}), "{FLG:railway}")

    def test_epoch_reset_is_converted_to_delay(self) -> None:
        self.assertEqual(retry_delay({"X-RateLimit-Reset": "1100"}, 1000), 1100.0)
        self.assertEqual(retry_delay({"X-RateLimit-Reset": "2000000000"}, 1999999995), 5.0)


if __name__ == "__main__":
    unittest.main()
