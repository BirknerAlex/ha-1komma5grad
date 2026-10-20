from homeassistant.components.number import NumberEntity
from homeassistant.const import PERCENTAGE
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DeviceType
from .coordinator import Coordinator
from .device_info import get_device_info


class EVTargetStateOfCharge(CoordinatorEntity[Coordinator], NumberEntity):
    """Number entity representing the SoC (0-100%) the EV should reach by its departure time."""

    def __init__(self, coordinator: Coordinator, system_id: str, ev_id: str) -> None:
        """Initialize the number entity."""

        super().__init__(coordinator)

        self._system_id = system_id
        self._ev_id = ev_id
        self._ev_name = ev_id

        # NumberEntity attributes
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 100.0
        self._attr_native_step = 1.0

        # Read initial state from already-fetched coordinator data
        ev_data = coordinator.get_ev_data(ev_id)
        if ev_data is not None:
            self._attr_native_value = ev_data.target_soc
            if ev_data.ev_name:
                self._ev_name = ev_data.ev_name
        else:
            self._attr_native_value = None

    @property
    def icon(self):
        return "mdi:battery-charging-high"

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        return f"{DOMAIN}_ev_target_soc_{self._system_id}_{self._ev_id}"

    @property
    def name(self) -> str:
        """Return the name of the EV target SoC entity."""
        return f"EV Target State of Charge {self._ev_name}"

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
    def native_value(self) -> float | None:
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the target SoC via the coordinator."""
        await self.hass.async_add_executor_job(
            self.coordinator.set_ev_target_soc, self._system_id, self._ev_id, value
        )

        # Update local value and write state
        self._attr_native_value = float(value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True when the API reports a target SoC, otherwise False so HA shows unavailable."""
        return self._attr_native_value is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        ev_data = self.coordinator.get_ev_data(self._ev_id)
        if ev_data is not None:
            self._attr_native_value = ev_data.target_soc
            if ev_data.ev_name:
                self._ev_name = ev_data.ev_name

        self.async_write_ha_state()
