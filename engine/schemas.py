"""Validated request bodies for the API. Bad input gets a 422, never a 500."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Id = Field(min_length=1, max_length=64)


class StaffLogin(BaseModel):
    pin: str = Field(min_length=1, max_length=32)


class AppLogin(BaseModel):
    token: str = Field(min_length=8, max_length=64)


class CallState(BaseModel):
    state: Literal["active", "ended"]
    kind: Literal["phone", "internet"] = "phone"


class CustomerRef(BaseModel):
    customer_id: str = Id


class NewRequest(BaseModel):
    action: str = Id
    details: dict[str, str | int | float] = Field(default_factory=dict)


class StandardChecks(BaseModel):
    passed: bool


class Override(BaseModel):
    requirement: Literal["liveness", "standard_checks"]
    reason: str = Field(min_length=3, max_length=300)
    agent: str = Field(default="agent", max_length=64)


class PasskeyVerify(BaseModel):
    credential: dict
    device: str = Field(default="phone", max_length=80)


class Decide(BaseModel):
    decision: Literal["approve", "decline"]
    credential: dict | None = None


class Pay(BaseModel):
    payee: str = Field(min_length=3, max_length=100)
    amount: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="", max_length=200)

    @field_validator("payee")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("payee is too short")
        return v


class AskFamily(BaseModel):
    family_id: str = Id


class Resolve(BaseModel):
    outcome: Literal["fraud_confirmed", "false_alarm", "callback"]
    analyst: str = Field(default="analyst", max_length=64)
    note: str = Field(default="", max_length=500)


class SimSwap(CustomerRef):
    on: bool = True
    hours_ago: float = Field(default=5, ge=0, le=24 * 30)


class Fri(BaseModel):
    number: str = Field(min_length=3, max_length=64)
    rating: Literal["Medium", "High", "Very High"] | None = None


class RecentCall(CustomerRef):
    on: bool = True
    minutes_ago: float = Field(default=2, ge=0, le=120)


class Consent(BaseModel):
    speaker: str = Field(pattern=r"^[a-z0-9_-]{2,32}$")
    name: str = Field(min_length=2, max_length=100)
    agree: bool
    languages: list[str] = Field(default_factory=list, max_length=10)
    clone: bool = False  # genuine-only volunteers are recorded but never cloned or used as a conversion source
    age_band: Literal["18-29", "30-44", "45-59", "60+"] | None = None  # optional, for false-alarm rates by group
    gender: Literal["female", "male", "other"] | None = None
