import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from src.negotiations import MAX_RESPONSE_BYTES, ProductIndex, make_handler, normalize
from s03e04 import TOOL_DESCRIPTION


CITIES = b"name,code\nWarszawa,WAW\nKrakow,KRK\nGdansk,GDA\n"
ITEMS = (
    "name,code\n"
    "Turbina wiatrowa 400W 48V,TUR\n"
    "Turbina wiatrowa 400W 24V,T24\n"
    "Akumulator AGM 48V 150Ah,AKU\n"
).encode()
CONNECTIONS = b"itemCode,cityCode\nTUR,WAW\nTUR,KRK\nT24,GDA\nAKU,KRK\n"


class ProductIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = ProductIndex.from_csv(CITIES, ITEMS, CONNECTIONS)

    def test_normalizes_diacritics_and_units(self):
        self.assertEqual(normalize("Potrzebuję 48 V"), "potrzebuje 48v")

    def test_registered_description_fits_hub_limit(self):
        self.assertLessEqual(len(TOOL_DESCRIPTION), 300)

    def test_matches_natural_description_and_numeric_variant(self):
        match = self.index.search("potrzebujemy turbiny wiatrowej o mocy 400 W i napięciu 48 V")
        self.assertEqual(match.item, "Turbina wiatrowa 400W 48V")
        self.assertEqual(match.cities, ("Krakow", "Warszawa"))

    def test_http_contract_and_byte_limit(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.index))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            body = json.dumps({"params": "akumulator AGM 48 V 150 Ah"})
            connection.request("POST", "/search", body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            payload = response.read()
            self.assertEqual(response.status, 200)
            self.assertLessEqual(len(payload), MAX_RESPONSE_BYTES)
            self.assertGreaterEqual(len(payload), 4)
            self.assertIn("Krakow", json.loads(payload)["output"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
