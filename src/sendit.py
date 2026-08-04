from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil


BASE_CAPACITY_KG = 1_000
ADDITIONAL_WAGON_CAPACITY_KG = 500
SYSTEM_FUNDED_CATEGORIES = frozenset({"A", "B"})


@dataclass(frozen=True, slots=True)
class ShippingDeclaration:
    sender_id: str
    origin: str
    destination: str
    route: str
    category: str
    description: str
    mass_kg: int
    shipping_date: date
    special_notes: str = "BRAK"

    def __post_init__(self) -> None:
        if not self.sender_id.isdigit():
            raise ValueError("sender_id must contain digits only")
        if self.category not in {"A", "B", "C", "D", "E"}:
            raise ValueError("category must be one of A, B, C, D or E")
        if not 1 <= self.mass_kg <= 4_000:
            raise ValueError("mass_kg must be between 1 and 4000")
        if not self.description or len(self.description) > 200:
            raise ValueError("description must contain between 1 and 200 characters")
        if not all((self.origin, self.destination, self.route)):
            raise ValueError("origin, destination and route cannot be empty")

    @property
    def additional_wagons(self) -> int:
        excess_kg = max(0, self.mass_kg - BASE_CAPACITY_KG)
        return ceil(excess_kg / ADDITIONAL_WAGON_CAPACITY_KG)

    @property
    def amount_due_pp(self) -> int:
        if self.category in SYSTEM_FUNDED_CATEGORIES:
            return 0
        raise ValueError("Fee calculation is only defined for system-funded categories")

    def render(self) -> str:
        return f"""SYSTEM PRZESYŁEK KONDUKTORSKICH - DEKLARACJA ZAWARTOŚCI
======================================================
DATA: {self.shipping_date.isoformat()}
PUNKT NADAWCZY: {self.origin}
------------------------------------------------------
NADAWCA: {self.sender_id}
PUNKT DOCELOWY: {self.destination}
TRASA: {self.route}
------------------------------------------------------
KATEGORIA PRZESYŁKI: {self.category}
------------------------------------------------------
OPIS ZAWARTOŚCI (max 200 znaków): {self.description}
------------------------------------------------------
DEKLAROWANA MASA (kg): {self.mass_kg}
------------------------------------------------------
WDP: {self.additional_wagons}
------------------------------------------------------
UWAGI SPECJALNE: {self.special_notes}
------------------------------------------------------
KWOTA DO ZAPŁATY: {self.amount_due_pp} PP
------------------------------------------------------
OŚWIADCZAM, ŻE PODANE INFORMACJE SĄ PRAWDZIWE.
BIORĘ NA SIEBIE KONSEKWENCJĘ ZA FAŁSZYWE OŚWIADCZENIE.
======================================================"""


def build_sendit_declaration(shipping_date: date | None = None) -> ShippingDeclaration:
    return ShippingDeclaration(
        sender_id="450202122",
        origin="Gdańsk",
        destination="Żarnowiec",
        route="X-01",
        category="A",
        description="kasety z paliwem do reaktora",
        mass_kg=2_800,
        shipping_date=shipping_date or date.today(),
    )
