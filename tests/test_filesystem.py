import unittest
import io
import zipfile

from src.filesystem import build_operations, parse_trade_data


class FilesystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        announcements = """
Opalino 45 chlebow, 120 butelek wody i 6 mlotkow.
Do Domatowa 60 makaronu, 150 butelek wody i 8 lopat.
Brudzewo: ryz 55 workow + 140 butelek wody + 5 wiertarek.
W Darzlubiu potrzeba 25 porcji wolowiny, 130 butelek wody i 7 kilofow.
Celbowo pyta o 40 porcji kurczaka, 125 butelek wody i 6 mlotkow.
Mechowo: ziemniaki 100 kg, kapusta 70, marchew 65 kg, woda 165, lopaty 9.
Puck potrzebuje 50 chlebow, 45 workow ryzu, 175 butelek wody i 7 wiertarek.
Karlinkowo: 52 makaronu, 22 porcje wolowiny, 95 kg ziemniakow, 155 butelek wody i 6 kilofow.
"""
        conversations = " ".join((
            "Natan Rams", "Iga Kapecka", "Rafal", "Kisiel", "Marta Frantz",
            "Oskar Radtke", "Eliza Redmann", "Damian Kroll", "Lena", "Konkel",
        ))
        transactions = """Domatowo -> chleb -> Opalino
Celbowo -> chleb -> Opalino
Brudzewo -> chleb -> Puck
Puck -> łopata -> Domatowo
Karlinkowo -> młotek -> Opalino
Domatowo -> ziemniaki -> Mechowo
"""
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("ogłoszenia.txt", announcements)
            zipped.writestr("rozmowy.txt", conversations)
            zipped.writestr("transakcje.txt", transactions)
        cls.data = parse_trade_data(archive.getvalue())
        cls.operations = build_operations(cls.data)

    def test_extracts_complete_trade_model(self):
        self.assertEqual(len(self.data.needs), 8)
        self.assertEqual(self.data.needs["Mechowo"]["woda"], 165)
        self.assertEqual(self.data.managers["Brudzewo"], "Rafal Kisiel")
        self.assertEqual(self.data.managers["Karlinkowo"], "Lena Konkel")
        self.assertEqual(self.data.sales["chleb"], ["Brudzewo", "Celbowo", "Domatowo"])

    def test_builds_three_directories_and_ascii_files(self):
        directories = [item["path"] for item in self.operations if item["action"] == "createDirectory"]
        self.assertEqual(directories, ["/miasta", "/osoby", "/towary"])
        self.assertTrue(all(path.isascii() for path in (item["path"] for item in self.operations)))
        city = next(item for item in self.operations if item["path"] == "/miasta/opalino")
        self.assertEqual(city["content"], '{"chleb":45,"woda":120,"mlotek":6}')
        person = next(item for item in self.operations if item["path"] == "/osoby/iga_kapecka")
        self.assertIn("[Opalino](/miasta/opalino)", person["content"])
        self.assertIn("/towary/lopata", (item["path"] for item in self.operations))
        self.assertIn("/towary/ziemniak", (item["path"] for item in self.operations))
        self.assertNotIn("/towary/ziemniaki", (item["path"] for item in self.operations))
        files = (item["path"].rsplit("/", 1)[-1] for item in self.operations if item["action"] == "createFile")
        self.assertTrue(all(name == name.lower() and "." not in name for name in files))


if __name__ == "__main__":
    unittest.main()
