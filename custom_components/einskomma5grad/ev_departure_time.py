from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DeviceType
from .coordinator import Coordinator, EVData
from .device_info import get_device_info


def _departure_time(ev_data: EVData) -> time | None:
    """Parse the departure time, which the API sends as HH:MM, sometimes with seconds."""
    if not ev_data.departure_time:
        return None
    try:
        return time.fromisoformat(ev_data.departure_time)
    except ValueError:
        return None


class EVDepartureTime(CoordinatorEntity[Coordinator], TimeEntity):
    """Time entity representing the time by which the EV should have reached its target SoC."""

    def __init__(self, coordinator: Coordinator, system_id: str, ev_id: str) -> None:
        """Initialize the time entity."""

        super().__init__(coordinator)

        self._system_id = system_id
        self._ev_id = ev_id
        self._ev_name = ev_id

        # Read initial state from already-fetched coordinator data
        ev_data = coordinator.get_ev_data(ev_id)
        if ev_data is not None:
            self._attr_native_value = _departure_time(ev_data)
            if ev_data.ev_name:
                self._ev_name = ev_data.ev_name
        else:
            self._attr_native_value = None

    @property
    def icon(self):
        return "mdi:car-clock"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}_ev_departure_time_{self._system_id}_{self._ev_id}"

    @property
    def name(self) -> str:
        """Return the name of the EV departure time entity."""
        return f"EV Departure Time {self._ev_name}"

    @property
    def device_info(self) -> DeviceInfo | None:
        ev_data = self.coordinator.get_ev_data(self._ev_id)
        return get_device_info(
            self.coordinator,
            self._system_id,
            DeviceType.EV_CHARGER,
            ev_data.assigned_charger_id if ev_data else None,
        )

    @property
    def native_value(self) -> time | None:
        return self._attr_native_value

    async def async_set_value(self, value: time) -> None:
        """Set the departure time via the coordinator."""
        await self.hass.async_add_executor_job(
            self.coordinator.set_ev_departure_time,
            self._system_id,
            self._ev_id,
            value.strftime("%H:%M"),
        )

        # Update local value and write state
        self._attr_native_value = value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True when the API reports a departure time, otherwise False so HA shows unavailable."""
        return self._attr_native_value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        ev_data = self.coordinator.get_ev_data(self._ev_id)
        if ev_data is not None:
            self._attr_native_value = _departure_time(ev_data)
            if ev_data.ev_name:
                self._ev_name = ev_data.ev_name

        self.async_write_ha_state()
