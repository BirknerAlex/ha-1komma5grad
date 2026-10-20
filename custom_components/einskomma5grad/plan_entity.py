"""Shared base for the entities that expose the plan of Heartbeat AI (battery, heat pump)."""

import datetime
from collections.abc import Coroutine
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HassJob, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api.optimizations import (
    ASSET_HEAT_PUMP,
    OptimizationWindow,
    active_window,
    merge_windows,
    upcoming_windows,
)
from .const import DOMAIN, DeviceType
from .coordinator import Coordinator
from .device_info import get_device_info
from .heat_pump_power_sensor import heat_pump_cards

# Upcoming windows exposed as attribute, enough for the next day at 15m slots
MAX_UPCOMING_WINDOWS = 96


def plan_attributes(
    slots: list[OptimizationWindow], now: datetime.datetime, asset: str
) -> dict:
    """Current decision and the planned windows of `asset`, adjacent slots merged.

    `market_price` (EUR/kWh) is the price of the current 15-minute slot, the
    prices in `upcoming` are averages over each merged window.
    """
    merged = merge_windows(slots)
    slot = active_window(slots, now, asset)
    window = active_window(merged, now, asset)
    upcoming = upcoming_windows(merged, now, asset)
    return {
        "decision": window.decision if window else None,
        "window_start": window.start.isoformat() if window else None,
        "window_end": window.end.isoformat() if window else None,
        "market_price": slot.market_price if slot else None,
        "upcoming": [w.as_dict() for w in upcoming[:MAX_UPCOMING_WINDOWS]],
    }


def has_heat_pump(coordinator: Coordinator, system_id: str) -> bool:
    """Whether the system has a heat pump, so that it makes sense to show its plan."""
    windows = coordinator.get_optimizations_by_id(system_id) or []
    return bool(heat_pump_cards(coordinator, system_id)) or any(
        window.asset == ASSET_HEAT_PUMP for window in windows
    )


class PlanEntity(CoordinatorEntity[Coordinator]):
    """An entity that reads the plan of one asset (subclasses set `_asset`)."""

    _asset: str
    _device_type: DeviceType

    def __init__(self, coordinator: Coordinator, system_id: str) -> None:
        super().__init__(coordinator)
        self._system_id = system_id

    def _windows(self) -> list[OptimizationWindow] | None:
        return self.coordinator.get_optimizations_by_id(self._system_id)

    @property
    def available(self) -> bool:
        """Unavailable until the optimizations could be fetched once."""
        return super().available and self._windows() is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        return get_device_info(self.coordinator, self._system_id, self._device_type)

    def _unique_id(self, key: str) -> str:
        return f"{DOMAIN}_{key}_{self._system_id}"


class PlanSlotEntity(PlanEntity):
    """A plan entity whose state changes whenever a 15-minute slot starts or ends.

    Home Assistant would otherwise only re-evaluate the state on the next poll.
    """

    def __init__(self, coordinator: Coordinator, system_id: str) -> None:
        super().__init__(coordinator, system_id)
        self._unsub_boundary: CALLBACK_TYPE | None = None
        self._boundary_job: HassJob[
            [datetime.datetime], Coroutine[Any, Any, None] | None
        ] = HassJob(
            self._handle_boundary, "plan slot boundary", cancel_on_shutdown=True
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_boundary_update()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_boundary_update()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._schedule_boundary_update()
        self.async_write_ha_state()

    @callback
    def _cancel_boundary_update(self) -> None:
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None

    @callback
    def _schedule_boundary_update(self) -> None:
        """Update the state when the next slot starts or ends.

        Uses the raw slots, not the merged windows: `market_price` follows the
        current slot, so it changes at slot boundaries inside a merged window.
        """
        self._cancel_boundary_update()
        now = dt_util.utcnow()
        boundaries = [
            moment
            for window in self._windows() or []
            if window.asset == self._asset
            for moment in (window.start, window.end)
            if moment > now
        ]
        if boundaries:
            self._unsub_boundary = async_track_point_in_utc_time(
                self.hass, self._boundary_job, min(boundaries)
            )

    @callback
    def _handle_boundary(self, _now: datetime.datetime) -> None:
        self._unsub_boundary = None
        self._schedule_boundary_update()
        self.async_write_ha_state()
