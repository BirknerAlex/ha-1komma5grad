"""Binary sensors: the battery decisions planned by Heartbeat AI.

Useful to coordinate loads Heartbeat does not control (e.g. a third-party
wallbox) with the battery: while Heartbeat keeps the battery from discharging,
such a load is covered from the grid instead of the battery.
"""

import datetime
from collections.abc import Coroutine
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api.optimizations import (
    ASSET_BATTERY,
    OptimizationWindow,
    active_window,
    battery_hold_active,
    merge_windows,
    upcoming_windows,
)
from .const import DOMAIN, DeviceType
from .coordinator import Coordinator
from .device_info import get_device_info

# Upcoming windows exposed as attribute, enough for the next day at 15m slots
MAX_UPCOMING_WINDOWS = 96


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator: Coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    async_add_entities(
        BatteryNoDischargeBinarySensor(coordinator, system.id())
        for system in coordinator.data.systems
    )


class BatteryNoDischargeBinarySensor(
    CoordinatorEntity[Coordinator], BinarySensorEntity
):
    """On while Heartbeat keeps the battery from discharging (or charges it from the grid).

    The state is re-evaluated at every window boundary, not only on polls.
    """

    def __init__(self, coordinator: Coordinator, system_id: str) -> None:
        super().__init__(coordinator)
        self._system_id = system_id
        self._unsub_boundary: CALLBACK_TYPE | None = None
        self._boundary_job: HassJob[
            [datetime.datetime], Coroutine[Any, Any, None] | None
        ] = HassJob(
            self._handle_boundary, "battery window boundary", cancel_on_shutdown=True
        )

    def _windows(self) -> list[OptimizationWindow] | None:
        return self.coordinator.get_optimizations_by_id(self._system_id)

    @property
    def name(self):
        return f"Battery No Discharge Active {self._system_id}"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_battery_no_discharge_active_{self._system_id}"

    @property
    def icon(self) -> str:
        return "mdi:battery-lock" if self.is_on else "mdi:battery-lock-open"

    @property
    def available(self) -> bool:
        """Unavailable until the optimizations could be fetched once."""
        return super().available and self._windows() is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        return get_device_info(self.coordinator, self._system_id, DeviceType.HYBRID)

    @property
    def is_on(self) -> bool | None:
        windows = self._windows()
        if windows is None:
            return None
        return battery_hold_active(windows, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict:
        """Current decision and the planned windows, adjacent slots merged.

        `market_price` (EUR/kWh) is the price of the current 15-minute slot, the
        prices in `upcoming` are averages over each merged window.
        """
        now = dt_util.utcnow()
        slots = self._windows() or []
        merged = merge_windows(slots)
        slot = active_window(slots, now)
        window = active_window(merged, now)
        upcoming = upcoming_windows(merged, now)
        return {
            "decision": window.decision if window else None,
            "window_start": window.start.isoformat() if window else None,
            "window_end": window.end.isoformat() if window else None,
            "market_price": slot.market_price if slot else None,
            "upcoming": [w.as_dict() for w in upcoming[:MAX_UPCOMING_WINDOWS]],
        }

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
            if window.asset == ASSET_BATTERY
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
