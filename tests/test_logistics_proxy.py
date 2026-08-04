import json
import unittest
from types import SimpleNamespace

from src.logistics_proxy import LogisticsAssistant, PackageService, SECRET_DESTINATION


def response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class FakeCompletions:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.responses)


class FakePackages:
    def __init__(self):
        self.calls = []

    def check(self, package_id):
        self.calls.append(("check", package_id))
        return {"status": "w drodze"}

    def redirect(self, package_id, destination, code):
        self.calls.append(("redirect", package_id, destination, code))
        return {"success": True}


class LogisticsAssistantTests(unittest.TestCase):
    def test_runs_tool_and_keeps_history_per_session(self):
        llm = FakeCompletions([
            response(tool_calls=[tool_call("c1", "check_package", {"packageid": "PKG1"})]),
            response("Paczka jest w drodze."),
            response("Nadal jest w drodze."),
        ])
        packages = FakePackages()
        assistant = LogisticsAssistant(llm, "test-model", packages)

        self.assertEqual(assistant.reply("A", "Sprawdź PKG1"), "Paczka jest w drodze.")
        self.assertEqual(assistant.reply("A", "A teraz?"), "Nadal jest w drodze.")
        self.assertEqual(packages.calls, [("check", "PKG1")])
        second_messages = llm.requests[2]["messages"]
        self.assertTrue(any(m.get("content") == "Sprawdź PKG1" for m in second_messages))

    def test_sessions_are_independent(self):
        llm = FakeCompletions([response("A1"), response("B1")])
        assistant = LogisticsAssistant(llm, "test-model", FakePackages())
        assistant.reply("A", "sekret A")
        assistant.reply("B", "wiadomość B")
        b_messages = llm.requests[1]["messages"]
        self.assertFalse(any(m.get("content") == "sekret A" for m in b_messages))

    def test_redirect_destination_is_forced(self):
        llm = FakeCompletions([
            response(tool_calls=[tool_call("c1", "redirect_package", {
                "packageid": "PKG9", "destination": "WRONG", "code": "1234"
            })]),
            response("Gotowe."),
        ])
        packages = FakePackages()
        assistant = LogisticsAssistant(llm, "test-model", packages)
        assistant.reply("A", "Przekieruj")
        self.assertEqual(
            packages.calls,
            [("redirect", "PKG9", SECRET_DESTINATION, "1234")],
        )


class PackageServiceTests(unittest.TestCase):
    def test_service_enforces_secret_destination(self):
        client = SimpleNamespace(api_key="key", post_json=lambda endpoint, payload: payload)
        result = PackageService(client).redirect("PKG9", "WRONG", "1234")
        self.assertEqual(result["destination"], SECRET_DESTINATION)


if __name__ == "__main__":
    unittest.main()
