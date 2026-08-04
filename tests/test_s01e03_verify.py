import os
import unittest
from unittest.mock import patch

import s01e03_verify


class VerifyHelpersTests(unittest.TestCase):
    def test_uses_configured_public_url(self):
        with patch.dict(os.environ, {"PROXY_PUBLIC_URL": "https://demo.ngrok.app/assistant/"}):
            self.assertEqual(
                s01e03_verify.discover_public_url(),
                "https://demo.ngrok.app/assistant",
            )

    def test_discovers_https_tunnel(self):
        with patch.dict(os.environ, {"PROXY_PUBLIC_URL": ""}), patch.object(
            s01e03_verify,
            "get_json",
            return_value={
                "tunnels": [
                    {"public_url": "http://demo.ngrok.app"},
                    {"public_url": "https://demo.ngrok.app"},
                ]
            },
        ):
            self.assertEqual(
                s01e03_verify.discover_public_url(),
                "https://demo.ngrok.app/assistant",
            )

    def test_builds_health_url(self):
        self.assertEqual(
            s01e03_verify.health_url("https://demo.ngrok.app/assistant"),
            "https://demo.ngrok.app/health",
        )


if __name__ == "__main__":
    unittest.main()
