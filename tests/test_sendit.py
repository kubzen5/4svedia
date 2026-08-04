from datetime import date
import unittest

from src.sendit import ShippingDeclaration, build_sendit_declaration


class SenditDeclarationTests(unittest.TestCase):
    def test_builds_expected_declaration(self) -> None:
        declaration = build_sendit_declaration(date(2026, 8, 4))

        self.assertEqual(declaration.route, "X-01")
        self.assertEqual(declaration.category, "A")
        self.assertEqual(declaration.additional_wagons, 4)
        self.assertEqual(declaration.amount_due_pp, 0)
        self.assertIn("DATA: 2026-08-04", declaration.render())
        self.assertIn("UWAGI SPECJALNE: BRAK", declaration.render())
        self.assertIn("KWOTA DO ZAPŁATY: 0 PP", declaration.render())

    def test_rejects_invalid_mass(self) -> None:
        with self.assertRaisesRegex(ValueError, "mass_kg"):
            ShippingDeclaration(
                sender_id="450202122",
                origin="Gdańsk",
                destination="Żarnowiec",
                route="X-01",
                category="A",
                description="kasety z paliwem do reaktora",
                mass_kg=4_001,
                shipping_date=date(2026, 8, 4),
            )


if __name__ == "__main__":
    unittest.main()
