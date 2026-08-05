import base64
import unittest

from src.phonecall import PhoneCallError, PhoneCallWorkflow, extract_audio, passable_roads


class FakeCodec:
    def __init__(self, transcripts):
        self.transcripts = iter(transcripts)
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)
        return text.encode()

    def transcribe(self, audio):
        return next(self.transcripts)


class FakeHub:
    api_key = "secret"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.payloads = []

    def post_json(self, endpoint, payload, **kwargs):
        self.payloads.append(payload)
        return next(self.responses)


def audio_response(value=b"audio"):
    return {"audio": base64.b64encode(value).decode()}


class PhoneCallTests(unittest.TestCase):
    def test_passable_roads_excludes_closed_ones(self):
        text = "RD224 jest zamknięta. RD472 jest przejezdna. RD820 jest zablokowana."
        self.assertEqual(passable_roads(text), ("RD472",))

    def test_passable_roads_understands_operator_route_recommendation(self):
        text = (
            "Droga RD-472 jest nieprzejezdna. Podobnie RD-224. "
            "Jedyne co ci zostało to jechać drogą RD-820. "
            "Tylko się upewnij, że masz terenówkę."
        )
        self.assertEqual(passable_roads(text), ("RD820",))

    def test_extract_audio_supports_nested_data_url(self):
        self.assertEqual(
            extract_audio({"answer": {"audio": "data:audio/mp3;base64,YWJj"}}), b"abc"
        )

    def test_workflow_obeys_turn_order_and_answers_challenges(self):
        hub = FakeHub([
            {}, audio_response(), audio_response(), audio_response(), audio_response(),
            {"audio": base64.b64encode(b"done").decode(), "message": "{FLG:OK}"},
        ])
        codec = FakeCodec([
            "Dzień dobry.",
            "RD224 zamknięta, RD472 przejezdna, RD820 zablokowana.",
            "Proszę podać hasło.",
            "Dlaczego monitoring ma zostać wyłączony?",
        ])

        result = PhoneCallWorkflow(hub, codec).run()

        self.assertEqual(result["message"], "{FLG:OK}")
        self.assertEqual(codec.spoken[0], "Dzień dobry, nazywam się Tymon Gajewski.")
        self.assertIn("RD224, RD472 i RD820", codec.spoken[1])
        self.assertEqual(codec.spoken[2], "Wyłącz proszę monitoring na RD-472.")
        self.assertEqual(codec.spoken[3], "BARBAKAN.")
        self.assertIn("transportu żywności", codec.spoken[4])
        self.assertTrue(all(set(call["answer"]) == {"audio"} for call in hub.payloads[1:]))

    def test_workflow_stops_if_status_is_ambiguous(self):
        hub = FakeHub([{}, audio_response(), audio_response()])
        codec = FakeCodec(["Dzień dobry.", "Nie mam danych."])
        with self.assertRaisesRegex(PhoneCallError, "No passable road"):
            PhoneCallWorkflow(hub, codec).run()

    def test_workflow_treats_sales_bot_provocation_as_auth_challenge(self):
        hub = FakeHub([
            {}, audio_response(), audio_response(), audio_response(), audio_response(),
            {"audio": base64.b64encode(b"done").decode(), "message": "{FLG:OK}"},
        ])
        codec = FakeCodec([
            "Jakiej sprawie dzwonisz?",
            "RD-472 jest nieprzejezdna. Jedyne co zostało to jechać drogą RD-820.",
            "Sorry, ale brzmisz jak bot od fotowoltaiki. Nic od ciebie nie kupię.",
            "Dlaczego mam wyłączyć monitoring?",
        ])

        result = PhoneCallWorkflow(hub, codec).run()

        self.assertEqual(result["message"], "{FLG:OK}")
        self.assertEqual(codec.spoken[-2], "BARBAKAN.")
        self.assertIn("transportu żywności", codec.spoken[-1])
        self.assertIn("nie może zostać odnotowana w logach", codec.spoken[-1])

    def test_workflow_answers_suspicion_provocation_with_password_first(self):
        hub = FakeHub([
            {}, audio_response(), audio_response(), audio_response(), audio_response(),
            {"audio": base64.b64encode(b"done").decode(), "message": "{FLG:OK}"},
        ])
        codec = FakeCodec([
            "Jakiej sprawie dzwonisz?",
            "RD-472 i RD-224 są nieprzejezdne. Jedź drogą RD-820.",
            "Powiem Ci, że to nie brzmi za dobrze. Coś kręcisz. Muszę to zgłosić.",
            "Po co wyłączać monitoring?",
        ])

        result = PhoneCallWorkflow(hub, codec).run()

        self.assertEqual(result["message"], "{FLG:OK}")
        self.assertEqual(codec.spoken[-2], "BARBAKAN.")
        self.assertIn("transportu żywności", codec.spoken[-1])

    def test_workflow_never_repeats_the_same_reason_in_a_loop(self):
        hub = FakeHub([
            {}, audio_response(), audio_response(), audio_response(), audio_response(),
            audio_response(),
        ])
        challenge = "Coś kręcisz. Muszę to zgłosić."
        codec = FakeCodec([
            "Jakiej sprawie dzwonisz?",
            "Jedź drogą RD-820.",
            challenge,
            challenge,
            challenge,
        ])

        with self.assertRaisesRegex(PhoneCallError, "after authentication and explanation"):
            PhoneCallWorkflow(hub, codec).run()

        reasons = [text for text in codec.spoken if "transportu żywności" in text]
        self.assertEqual(len(reasons), 1)


if __name__ == "__main__":
    unittest.main()
