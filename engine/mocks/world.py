"""Mock core banking, DoT FRI and telco SIM-swap feeds.

These stand in for the real integrations named in the deck (core banking, FRI via DIP,
a telco SIM-swap API). The demo panel can flip any of them live.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

DAY = 86400.0


@dataclass
class Customer:
    id: str
    name: str
    age: int
    city: str
    language: str
    registered_mobile: str
    account_no: str
    balance: float
    upi_id: str
    usual_upi_max: float
    known_payees: list[str]
    family_circle: list[str] = field(default_factory=list)  # customer ids who can be pinged
    opted_in_guard: bool = True


SEED: dict[str, Customer] = {
    "rahul": Customer(
        id="rahul",
        name="Rahul Sharma",
        age=29,
        city="Bengaluru",
        language="en-IN",
        registered_mobile="+919845012210",
        account_no="50100231187210",
        balance=184_250.0,
        upi_id="rahul.sharma@cbank",
        usual_upi_max=25_000,
        known_payees=["sunita.sharma@cbank", "landlord.blr@okaxis"],
        family_circle=["sunita"],
    ),
    "sunita": Customer(
        id="sunita",
        name="Sunita Sharma",
        age=62,
        city="Lucknow",
        language="hi-IN",
        registered_mobile="+919415033618",
        account_no="50100110094618",
        balance=312_900.0,
        upi_id="sunita.sharma@cbank",
        usual_upi_max=5_000,
        known_payees=["rahul.sharma@cbank", "doodhwala.lko@okicici", "medplus.lko@ybl"],
        family_circle=["rahul"],
    ),
}

# Numbers the demo and the IndiaCall simulator use besides the registered ones.
FRAUD_PHONE = "+917000012345"  # rated High on FRI: an attacker calling from their own number
SPARE_PHONE = "+919886045120"  # unregistered and unrated: a genuine customer on a family member's phone

# FRI as DoT shares it: Medium / High / Very High per mobile number (absent = not rated).
FRI_SEED = {
    "+918877665544": "Very High",
    FRAUD_PHONE: "High",
    "quickhelp.relief@okaxis": "High",  # UPI handle linked to a high-FRI number
}


class World:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.customers = copy.deepcopy(SEED)
        self.fri = dict(FRI_SEED)
        self.sim_swaps: dict[str, float] = {}  # mobile -> unix time of last swap
        self.app_sessions: dict[str, float] = {}  # customer id -> last seen in app
        self.recent_calls: dict[str, float] = {}  # customer id -> time a phone call ended (guard trigger)
        self.on_call: dict[str, str] = {}  # customer id -> "phone" | "internet", while the CS Bank app sees a call
        self.calls_by_customer: dict[str, list[float]] = {}

    # ---- core banking
    def customer(self, cid: str) -> Customer | None:
        return self.customers.get(cid)

    def by_mobile(self, mobile: str) -> Customer | None:
        return next((c for c in self.customers.values() if c.registered_mobile == mobile), None)

    # ---- DoT FRI
    def fri_rating(self, key: str | None) -> str | None:
        return self.fri.get(key or "")

    # ---- telco
    def sim_swapped_within(self, mobile: str, seconds: float) -> bool:
        t = self.sim_swaps.get(mobile)
        return t is not None and time.time() - t < seconds

    def public(self) -> dict:
        return {
            "customers": {k: c.__dict__ for k, c in self.customers.items()},
            "fri": self.fri,
            "sim_swaps": self.sim_swaps,
            "recent_calls": self.recent_calls,
            "on_call": self.on_call,
        }


world = World()
