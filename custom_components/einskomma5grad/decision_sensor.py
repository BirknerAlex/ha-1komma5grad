"""Sensors with the decision Heartbeat AI currently has planned for an asset."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.util import dt as dt_util

from .api.optimizations import (
    ASSET_BATTERY,
    ASSET_HEAT_PUMP,
    NO_DECISION,
    active_window,
    merge_windows,
)
from .const import DeviceType
from .plan_entity import PlanSlotEntity, plan_attributes


class OptimizationDecisionSensor(PlanSlotEntity, SensorEntity):
    """The current decision, e.g. `BATTERY_NO_DISCHARGE`, or `NONE`.

    The decision is reported as sent by the API, so decisions this integration
    does not know yet show up as they are. The window, the market price of the
    current slot and the planned windows are attributes.
    """

    _title: str
    _key: str
    _icon: str

    @property
    def name(self) -> str:
        return f"{self._title} Optimization Decision {self._system_id}"

    @property
    def unique_id(self) -> str:
        return self._unique_id(f"{self._key}_optimization_decision")

    @property
    def icon(self) -> str:
        return self._icon

    @property
    def native_value(self) -> str | None:
        windows = self._windows()
        if windows is None:
            return None
        window = active_window(merge_windows(windows), dt_util.utcnow(), self._asset)
        return window.decision if window else NO_DECISION

    @property
    def extra_state_attributes(self) -> dict:
        # The decision is the state of this entity already.
        attributes = plan_attributes(
            self._windows() or [], dt_util.utcnow(), self._asset
        )
        del attributes["decision"]
        return attributes


class BatteryOptimizationDecisionSensor(OptimizationDecisionSensor):
    _asset = ASSET_BATTERY
    _device_type = DeviceType.HYBRID
    _title = "Battery"
    _key = "battery"
    _icon = "mdi:battery-sync"


class HeatPumpOptimizationDecisionSensor(OptimizationDecisionSensor):
    _asset = ASSET_HEAT_PUMP
    _device_type = DeviceType.HEAT_PUMP
    _title = "Heat Pump"
    _key = "heat_pump"
    _icon = "mdi:heat-pump"
