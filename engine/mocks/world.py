"""Mock core banking, DoT FRI and telco SIM-swap feeds.

These stand in for the real integrations named in the deck (core banking, FRI via DIP,
a telco SIM-swap API). Customers are kept in SQLite, so accounts judges open in the CS Bank
app and the families they form survive an engine restart. Call state, FRI ratings and SIM
swaps are live signals and stay in memory.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import time
from dataclasses import dataclass, field

from engine.db import db

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
    # other customer id -> {"label": what this customer calls them, "since": when the link was made}
    family: dict[str, dict] = field(default_factory=dict)
    check_channel: str = "notify"  # how family checks reach this customer: "ring" | "notify"
    share_call_status: bool = False  # tell family "on a call: yes/no", only while they are checking with me
    card_last4: str = ""

    @property
    def first_name(self) -> str:
        return self.name.split()[0]

    def label_for(self, other_id: str) -> str:
        """What this customer calls `other_id` ("Mom", "Rahul"), else the other's first name."""
        link = self.family.get(other_id) or {}
        other = world.customer(other_id)
        return link.get("label") or (other.first_name if other else other_id)


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
        family={"sunita": {"label": "Mom", "since": 0.0}},
        check_channel="ring",
        share_call_status=True,
        card_last4="4417",
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
        family={"rahul": {"label": "Rahul", "since": 0.0}},
        check_channel="ring",
        share_call_status=True,
        card_last4="9061",
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

_FIELDS = {f.name for f in dataclasses.fields(Customer)}


def _from_row(data: dict) -> Customer:
    return Customer(**{k: v for k, v in data.items() if k in _FIELDS})


class World:
    def __init__(self):
        self.customers: dict[str, Customer] = {}
        for r in db.query("SELECT data FROM customers ORDER BY created_at"):
            c = _from_row(json.loads(r["data"]))
            self.customers[c.id] = c
        self.reset()

    def reset(self) -> None:
        """Demo reset: the seeded accounts go back to their seed. Accounts opened in the app stay,
        but lose links to the seeded ones."""
        for cid, seed in SEED.items():
            self.customers[cid] = copy.deepcopy(seed)
            self.save(self.customers[cid])
        for c in self.customers.values():
            if c.id not in SEED and any(f in SEED for f in c.family):
                c.family = {k: v for k, v in c.family.items() if k not in SEED}
                self.save(c)
        self.fri = dict(FRI_SEED)
        self.sim_swaps: dict[str, float] = {}  # mobile -> unix time of last swap
        self.app_sessions: dict[str, float] = {}  # customer id -> last seen in app
        self.recent_calls: dict[str, float] = {}  # customer id -> time a phone call ended (guard trigger)
        # customer id -> {"kind": "phone" | "internet", "direction": "incoming" | "outgoing" | "unknown", "since": t}
        self.on_call: dict[str, dict] = {}
        self.calls_by_customer: dict[str, list[float]] = {}

    # ---- core banking
    def customer(self, cid: str) -> Customer | None:
        return self.customers.get(cid)

    def by_mobile(self, mobile: str) -> Customer | None:
        return next((c for c in self.customers.values() if c.registered_mobile == mobile), None)

    def by_upi(self, upi: str) -> Customer | None:
        return next((c for c in self.customers.values() if c.upi_id == upi), None)

    def add(self, c: Customer) -> Customer:
        self.customers[c.id] = c
        self.save(c)
        return c

    def save(self, c: Customer) -> None:
        db.execute(
            "INSERT INTO customers (id, data, created_at) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            [c.id, json.dumps(dataclasses.asdict(c)), time.time()],
        )

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
