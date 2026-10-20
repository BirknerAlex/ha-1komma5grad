"""Heartbeat AI optimization windows (planned battery and heat pump decisions).

Parsed from `GET /api/v1/heartbeat-ai/optimizations`. Each event describes a
15-minute slot and what Heartbeat decided for one asset in it, e.g. that the
battery must not discharge or is charged from the grid. Kept free of Home
Assistant imports so it can be tested on its own.

Observed behaviour of the endpoint: the plan only reaches a few hours ahead,
events whose `from` is earlier than `to - 48h` are dropped, and a `to` much
further than two days ahead returns nothing.
"""

import datetime
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .system import System

OPTIMIZATIONS_PATH = "/api/v1/heartbeat-ai/optimizations"

ASSET_BATTERY = "BATTERY"
ASSET_HEAT_PUMP = "HEATPUMP"

# Decisions during which the home battery is not discharged, so additional load
# (e.g. a wallbox Heartbeat does not control) is covered from the grid.
BATTERY_HOLD_DECISIONS = frozenset({"BATTERY_NO_DISCHARGE", "BATTERY_CHARGE_FROM_GRID"})

# State of the decision sensors while Heartbeat has planned nothing for the asset.
NO_DECISION = "NONE"

_ASSET_NAMES = {ASSET_BATTERY: "Battery", ASSET_HEAT_PUMP: "Heat pump"}

# The API sends `marketPrice.value` in EUR/MWh; the integration uses EUR/kWh.
MWH_PER_KWH = 1000


@dataclass(frozen=True)
class OptimizationWindow:
    """One planned decision for one asset; market price in EUR/kWh."""

    asset: str
    decision: str
    start: datetime.datetime
    end: datetime.datetime
    market_price: float | None = None
    state_of_charge: int | None = None

    def is_active(self, now: datetime.datetime) -> bool:
        return self.start <= now < self.end

    def as_dict(self) -> dict:
        return {
            "decision": self.decision,
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "market_price": self.market_price,
        }


def decision_label(asset: str, decision: str) -> str:
    """Readable title such as "Battery: no discharge", also for unknown decisions."""
    name = _ASSET_NAMES.get(asset, asset.replace("_", " ").capitalize())
    readable = decision.removeprefix(f"{asset}_").replace("_", " ").lower()
    return f"{name}: {readable}"


def _parse_time(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    # The API sends UTC; treat a missing offset as UTC as well.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def _to_eur_per_kwh(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value / MWH_PER_KWH, 5)


def parse_windows(response) -> list[OptimizationWindow]:
    """Return all well-formed slots, sorted by start. Malformed events are skipped."""
    events = response.get("events") if isinstance(response, dict) else None
    windows: list[OptimizationWindow] = []
    for event in events or []:
        data = event.get("data") if isinstance(event, dict) else None
        if not isinstance(data, dict):
            continue
        start = _parse_time(data.get("from"))
        end = _parse_time(data.get("to"))
        asset = data.get("asset")
        decision = data.get("decision")
        if start is None or end is None or end <= start:
            continue
        if not isinstance(asset, str) or not isinstance(decision, str):
            continue
        price = data.get("marketPrice")
        soc = data.get("stateOfCharge")
        windows.append(
            OptimizationWindow(
                asset=asset,
                decision=decision,
                start=start,
                end=end,
                market_price=_to_eur_per_kwh(
                    price.get("value") if isinstance(price, dict) else None
                ),
                state_of_charge=soc if isinstance(soc, int) else None,
            )
        )
    windows.sort(key=lambda w: w.start)
    return windows


def merge_windows(windows: list[OptimizationWindow]) -> list[OptimizationWindow]:
    """Join adjacent or overlapping slots with the same asset and decision.

    The merged window carries the average market price of its slots and the state
    of charge of its first slot.
    """
    merged: list[OptimizationWindow] = []
    prices: list[list[float]] = []
    for window in sorted(windows, key=lambda w: (w.asset, w.start)):
        last = merged[-1] if merged else None
        if (
            last is not None
            and last.asset == window.asset
            and last.decision == window.decision
            and window.start <= last.end
        ):
            merged[-1] = replace(last, end=max(last.end, window.end))
        else:
            merged.append(window)
            prices.append([])
        if window.market_price is not None:
            prices[-1].append(window.market_price)
    result = [
        replace(w, market_price=round(sum(p) / len(p), 5) if p else None)
        for w, p in zip(merged, prices, strict=True)
    ]
    result.sort(key=lambda w: w.start)
    return result


def active_window(
    windows: list[OptimizationWindow],
    now: datetime.datetime,
    asset: str = ASSET_BATTERY,
) -> OptimizationWindow | None:
    """Return the window of `asset` that covers `now`, if any."""
    return next((w for w in windows if w.asset == asset and w.is_active(now)), None)


def upcoming_windows(
    windows: list[OptimizationWindow],
    now: datetime.datetime,
    asset: str = ASSET_BATTERY,
) -> list[OptimizationWindow]:
    """Return the windows of `asset` that start after `now`, in order."""
    return [w for w in windows if w.asset == asset and w.start > now]


def battery_hold_active(
    windows: list[OptimizationWindow], now: datetime.datetime
) -> bool:
    """Whether Heartbeat currently keeps the battery from discharging."""
    window = active_window(windows, now)
    return window is not None and window.decision in BATTERY_HOLD_DECISIONS


def fetch_optimizations(
    system: "System", start: datetime.datetime, end: datetime.datetime
):
    """GET the decisions for windows within the range, raising RequestError on failure."""
    return system._get_json(
        system.client.HEARTBEAT_API + OPTIMIZATIONS_PATH,
        "Heartbeat AI optimizations",
        {
            "siteId": system.id(),
            "from": start.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
