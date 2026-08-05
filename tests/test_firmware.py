from __future__ import annotations

import unittest

from src.firmware import FirmwareError, find_confirmation, validate_command


class FirmwareTests(unittest.TestCase):
    def test_finds_confirmation(self) -> None:
        code = "ECCS-0123456789abcdef0123456789abcdef01234567"
        self.assertEqual(find_confirmation({"output": f"success: {code}"}), code)

    def test_rejects_forbidden_paths(self) -> None:
        for command in ("ls /etc", "cat /root/key", "find /proc/"):
            with self.subTest(command=command), self.assertRaises(FirmwareError):
                validate_command(command)

    def test_accepts_firmware_path(self) -> None:
        validate_command("/opt/firmware/cooler/cooler.bin")


if __name__ == "__main__":
    unittest.main()
