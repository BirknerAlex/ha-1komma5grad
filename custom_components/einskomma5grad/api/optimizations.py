"""Heartbeat AI optimization windows (planned battery and heat pump decisions).

Parsed from `GET /api/v1/heartbeat-ai/optimizations`. Each event describes a time
window and what Heartbeat decided for one asset in it, e.g. that the battery must
not discharge or is charged from the grid. Kept free of Home Assistant imports so
it can be tested on its own.
"""

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .system import System

OPTIMIZATIONS_PATH = "/api/v1/heartbeat-ai/optimizations"

ASSET_BATTERY = "BATTERY"

# Decisions during which the home battery is not discharged, so additional load
# (e.g. a wallbox Heartbeat does not control) is covered from the grid.
BATTERY_HOLD_DECISIONS = frozenset({"BATTERY_NO_DISCHARGE", "BATTERY_CHARGE_FROM_GRID"})


@dataclass(frozen=True)
class OptimizationWindow:
    """One planned decision for one asset."""

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


def _parse_time(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # The API sends UTC; treat a missing offset as UTC as well.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)


def parse_windows(response) -> list[OptimizationWindow]:
    """Return all well-formed windows, sorted by start. Malformed events are skipped."""
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
        price_value = price.get("value") if isinstance(price, dict) else None
        soc = data.get("stateOfCharge")
        windows.append(
            OptimizationWindow(
                asset=asset,
                decision=decision,
                start=start,
                end=end,
                market_price=float(price_value)
                if isinstance(price_value, (int, float))
                else None,
                state_of_charge=soc if isinstance(soc, int) else None,
            )
        )
    windows.sort(key=lambda w: w.start)
    return windows


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
