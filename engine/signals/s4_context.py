"""S4: context risk. Never uses audio. Can raise the voice tier one step, never lower it."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from engine.mocks.world import DAY, world

SIM_SWAP_WINDOW = 3 * DAY  # deck: SIM swap in the last 72 h


@dataclass
class ContextResult:
    flags: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def raises(self) -> bool:
        return bool(self.flags)


def evaluate(customer_id: str | None, caller_cli: str | None) -> ContextResult:
    res = ContextResult()
    cust = world.customer(customer_id) if customer_id else None
    rating = world.fri_rating(caller_cli)
    res.info["caller_cli"] = caller_cli
    res.info["fri"] = rating
    if rating in ("High", "Very High"):
        res.flags.append("FRI_HIGH")
    if cust is None:
        return res
    res.info["registered_mobile"] = cust.registered_mobile
    if caller_cli and caller_cli != cust.registered_mobile:
        res.flags.append("CLI_MISMATCH")
    if world.sim_swapped_within(cust.registered_mobile, SIM_SWAP_WINDOW):
        res.flags.append("SIM_SWAP_RECENT")
    recent = [t for t in world.calls_by_customer.get(cust.id, []) if time.time() - t < DAY]
    res.info["calls_24h"] = len(recent)
    if len(recent) >= 3:
        res.flags.append("REPEAT_CALLS")
    seen = world.app_sessions.get(cust.id)
    res.info["live_app_session"] = bool(seen and time.time() - seen < 120)
    return res
