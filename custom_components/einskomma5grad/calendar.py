"""Calendars with the windows planned by Heartbeat AI."""

import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api.optimizations import (
    ASSET_BATTERY,
    ASSET_HEAT_PUMP,
    OptimizationWindow,
    decision_label,
    merge_windows,
)
from .const import DOMAIN, DeviceType
from .coordinator import Coordinator
from .plan_entity import PlanEntity, has_heat_pump


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendars."""
    coordinator: Coordinator = hass.data[DOMAIN][config_entry.entry_id].coordinator

    calendars: list[PlanCalendar] = []
    for system in coordinator.data.systems:
        calendars.append(BatteryPlanCalendar(coordinator, system.id()))
        if has_heat_pump(coordinator, system.id()):
            calendars.append(HeatPumpPlanCalendar(coordinator, system.id()))
    async_add_entities(calendars)


def _event(window: OptimizationWindow) -> CalendarEvent:
    description = f"Decision: {window.decision}"
    if window.market_price is not None:
        description += f"\nMarket price: {window.market_price} EUR/kWh"
    return CalendarEvent(
        start=window.start,
        end=window.end,
        summary=decision_label(window.asset, window.decision),
        description=description,
    )


class PlanCalendar(PlanEntity, CalendarEntity):
    """The planned decisions of one asset as events, adjacent 15-minute slots merged.

    Only the part of the plan that was fetched is available: a few hours ahead
    and the last 12 hours. The calendar is `on` while any window is active.
    """

    _title: str
    _key: str
    _icon: str

    def _asset_windows(self) -> list[OptimizationWindow]:
        return [
            window
            for window in merge_windows(self._windows() or [])
            if window.asset == self._asset
        ]

    @property
    def name(self) -> str:
        return f"{self._title} Plan {self._system_id}"

    @property
    def unique_id(self) -> str:
        return self._unique_id(f"{self._key}_plan")

    @property
    def icon(self) -> str:
        return self._icon

    @property
    def event(self) -> CalendarEvent | None:
        """The current window or, if there is none, the next one."""
        now = dt_util.utcnow()
        coming = [w for w in self._asset_windows() if w.end > now]
        return _event(coming[0]) if coming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        return [
            _event(window)
            for window in self._asset_windows()
            if window.start < end_date and window.end > start_date
        ]


class BatteryPlanCalendar(PlanCalendar):
    _asset = ASSET_BATTERY
    _device_type = DeviceType.HYBRID
    _title = "Battery"
    _key = "battery"
    _icon = "mdi:battery-clock"


class HeatPumpPlanCalendar(PlanCalendar):
    _asset = ASSET_HEAT_PUMP
    _device_type = DeviceType.HEAT_PUMP
    _title = "Heat Pump"
    _key = "heat_pump"
    _icon = "mdi:heat-pump"
