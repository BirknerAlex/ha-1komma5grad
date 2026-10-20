"""Binary sensors: the battery decisions planned by Heartbeat AI.

Useful to coordinate loads Heartbeat does not control (e.g. a third-party
wallbox) with the battery: while Heartbeat keeps the battery from discharging,
such a load is covered from the grid instead of the battery.
"""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api.optimizations import ASSET_BATTERY, battery_hold_active
from .const import DOMAIN, DeviceType
from .coordinator import Coordinator
from .plan_entity import PlanSlotEntity, plan_attributes


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


class BatteryNoDischargeBinarySensor(PlanSlotEntity, BinarySensorEntity):
    """On while Heartbeat keeps the battery from discharging (or charges it from the grid).

    The state is re-evaluated at every slot boundary, not only on polls.
    """

    _asset = ASSET_BATTERY
    _device_type = DeviceType.HYBRID

    @property
    def name(self):
        return f"Battery No Discharge Active {self._system_id}"

    @property
    def unique_id(self) -> str:
        return self._unique_id("battery_no_discharge_active")

    @property
    def icon(self) -> str:
        return "mdi:battery-lock" if self.is_on else "mdi:battery-lock-open"

    @property
    def is_on(self) -> bool | None:
        windows = self._windows()
        if windows is None:
            return None
        return battery_hold_active(windows, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict:
        return plan_attributes(self._windows() or [], dt_util.utcnow(), self._asset)
