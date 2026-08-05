import unittest

from src.okoeditor import KOMAROWO_INCIDENT_ID, SKOLWIN_RECORD_ID, apply_updates, required_updates


class FakeHub:
    api_key = "test-key"

    def __init__(self):
        self.calls = []

    def post_json(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        return {"status": "success"}


class OkoEditorTests(unittest.TestCase):
    def test_builds_required_classifications_and_task_status(self):
        updates = required_updates()
        self.assertEqual(updates[0].record_id, SKOLWIN_RECORD_ID)
        self.assertTrue(updates[0].title.startswith("MOVE04 "))
        self.assertNotIn("ludzi", updates[0].content)
        self.assertNotIn("pojazd", updates[0].content)
        self.assertEqual(updates[1].done, "YES")
        self.assertIn("bobry", updates[1].content)
        self.assertEqual(updates[2].record_id, KOMAROWO_INCIDENT_ID)
        self.assertTrue(updates[2].title.startswith("MOVE01 "))
        self.assertIn("Komarowo", updates[2].title)

    def test_applies_updates_then_calls_done(self):
        hub = FakeHub()
        responses = apply_updates(hub)  # type: ignore[arg-type]
        self.assertEqual(len(responses), 4)
        self.assertEqual([call[0] for call in hub.calls], ["verify"] * 4)
        self.assertEqual(hub.calls[-1][1]["answer"], {"action": "done"})
        self.assertTrue(all(call[1]["task"] == "okoeditor" for call in hub.calls))


if __name__ == "__main__":
    unittest.main()
