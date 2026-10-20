from collections import defaultdict
from datetime import UTC, datetime, timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CURRENCY_ICON, DOMAIN, DeviceType
from .coordinator import Coordinator
from .device_info import get_device_info

# The timeseries keys of the price endpoint are true UTC (the "Z" is right), and
# each key labels the END of its 15 minute slot: the price valid from 21:15 to 21:30
# UTC is stored under "21:30Z". Hourly resolution works the same way (the key is
# the end of the hour). Verified against the Heartbeat app and the Heartbeat AI
# optimizations, whose slot [22:00, 22:15) carries the price of the key "22:15Z".
SLOT = timedelta(minutes=15)


def slot_start(now: datetime) -> datetime:
    """Return the start (UTC) of the 15 minute slot that `now` falls into."""
    now_utc = now.astimezone(UTC)
    return now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0)


def current_slot_key() -> str:
    """Return the timeseries key of the current 15 minute price slot."""
    return (slot_start(dt_util.now()) + SLOT).strftime("%Y-%m-%dT%H:%MZ")


class ElectricityPriceSensor(CoordinatorEntity[Coordinator], SensorEntity):
    """Representation of an Energy Price Sensor."""

    def __init__(self, coordinator: Coordinator, system_id: str) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)

        self._system_id = system_id
        self._prices = {}
        self._price_summary = {}
        self._unit = '€/kWh' # Default unit

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return CURRENCY_ICON

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"Electricity Price {self._system_id}"

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.  Think carefully what you want this to be as
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}_electricity_price_{self._system_id}"

    @property
    def native_value(self) -> None | float:
        """Return the state of the entity."""

        current_time = current_slot_key()

        if current_time in self._prices:
            current_price_data = self._prices.get(current_time)
            if current_price_data and "marketPriceWithGridCostAndVat" in current_price_data:
                return round(float(current_price_data["marketPriceWithGridCostAndVat"]), 4)

        return None

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return UnitOfEnergy.KILO_WATT_HOUR

    @property
    def device_info(self) -> DeviceInfo | None:
        return get_device_info(self.coordinator, self._system_id, DeviceType.GATEWAY)

    @property
    def extra_state_attributes(self) -> dict:
        """Return forecast and summary price attributes."""
        attrs = {}

        if not self._prices:
            return attrs

        current_start = slot_start(dt_util.now())

        # Build forecast list: future 15-min slots, sorted chronologically.
        # A key is the END of its slot (UTC), so the slot starts 15 minutes earlier.
        forecast = []
        for timestamp_str, price_data in sorted(self._prices.items()):
            try:
                start = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%MZ").replace(
                    tzinfo=UTC
                ) - SLOT
            except (ValueError, TypeError):
                continue

            if start <= current_start:
                continue

            price_value = price_data.get("marketPriceWithGridCostAndVat")
            if price_value is not None:
                forecast.append({
                    "datetime": start.isoformat(),
                    "price": round(float(price_value), 4),
                })

        attrs["forecast"] = forecast

        # Summary statistics from the API response
        try:
            summary = self._price_summary["energyMarketWithGridCostsAndVat"]
            attrs["price_today_min"] = round(float(summary["lowestPrice"]["price"]["amount"]), 4)
            attrs["price_today_max"] = round(float(summary["highestPrice"]["price"]["amount"]), 4)
            attrs["price_today_avg"] = round(float(summary["averagePrice"]["price"]["amount"]), 4)
        except (KeyError, TypeError, ValueError):
            pass

        # Cheapest upcoming hour (average of 4 × 15-min slots per hour)
        if forecast:
            hourly_prices = defaultdict(list)
            for entry in forecast:
                hour_start = datetime.fromisoformat(entry["datetime"]).replace(minute=0)
                hourly_prices[hour_start].append(entry["price"])

            # Only consider hours with all 4 slots for a fair average
            complete_hours = {
                hour: sum(prices) / len(prices)
                for hour, prices in hourly_prices.items()
                if len(prices) == 4
            }
            if complete_hours:
                cheapest_hour = min(complete_hours, key=lambda h: complete_hours[h])
                attrs["cheapest_upcoming_hour"] = cheapest_hour.isoformat()
                attrs["cheapest_upcoming_price"] = round(complete_hours[cheapest_hour], 4)

        attrs["forecast_hours_available"] = len(forecast)

        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        prices = self.coordinator.get_prices_by_id(self._system_id)

        if prices is None or "timeseries" not in prices:
            self.coordinator.logger.error("Timeseries data not found in coordinator data")
            return

        self._prices = prices["timeseries"]
        self._price_summary = prices

        # Determine currency from response metadata
        try:
            currency = prices["timeseriesMetadata"]["units"]["price"]["currency"]
            per_unit = prices["timeseriesMetadata"]["units"]["price"]["perUnit"]
            self._unit = f"{currency}/{per_unit}"
        except (KeyError, TypeError):
            self._unit = "€/kWh"

        self.async_write_ha_state()
