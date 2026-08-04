from src.mailbox import ZmailClient, extract_facts


def test_extract_facts_prefers_corrected_confirmation_code() -> None:
    wrong = "SEC-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    correct = "SEC-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    messages = [
        {"subject": "Nowe hasło", "message": "Logować się hasłem:\nRABARBAR25"},
        {"subject": "Akcja", "message": f"Atak planujemy 2026-03-23. kod: {wrong}"},
        {"subject": "Korekta", "message": f"Zły kod. Poprawny to: {correct}"},
    ]

    facts = extract_facts(messages)

    assert facts.passwords == ("RABARBAR25",)
    assert facts.dates == ("2026-03-23",)
    assert facts.confirmation_codes == (correct, wrong)


class ActiveInboxStub(ZmailClient):
    def __init__(self) -> None:
        self.refreshed = False

    def get_thread(self, thread_id: int):
        self.refreshed = True
        assert thread_id == 42
        return [{"messageID": "fresh-id"}]

    def get_messages(self, ids):
        assert self.refreshed
        assert ids == ["fresh-id"]
        return [{"message": "fresh body"}]


def test_read_search_results_refreshes_active_thread_ids() -> None:
    client = ActiveInboxStub()
    assert client.read_search_results([{"threadID": 42, "messageID": "stale-id"}]) == [
        {"message": "fresh body"}
    ]
