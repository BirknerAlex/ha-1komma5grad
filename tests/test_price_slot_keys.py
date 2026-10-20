"""Tests for how the price sensor maps the current time to the API's slot keys.

The timeseries keys are UTC and label the END of each 15 minute slot. The numbers
below come from the live API and the Heartbeat app on 2026-10-20 (Berlin was on
summer time, UTC+2): at about 21:22 UTC the app showed 39.1 ct/kWh, which is the
key 21:30Z, the slot 21:15-21:30.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.einskomma5grad.sensor_electricity_price import (
    ElectricityPriceSensor,
    current_slot_key,
)

NOW_PATH = "custom_components.einskomma5grad.sensor_electricity_price.dt_util.now"

# Keys and all-in prices (EUR/kWh) as returned by the API for the evening
REAL_PRICES = {
    "2026-10-20T21:00Z": {"marketPriceWithGridCostAndVat": "0.3883803"},
    "2026-10-20T21:15Z": {"marketPriceWithGridCostAndVat": "0.400078"},
    "2026-10-20T21:30Z": {"marketPriceWithGridCostAndVat": "0.3905104"},
    "2026-10-20T21:45Z": {"marketPriceWithGridCostAndVat": "0.3875116"},
    "2026-10-20T22:00Z": {"marketPriceWithGridCostAndVat": "0.3726961"},
    "2026-10-20T22:15Z": {"marketPriceWithGridCostAndVat": "0.3605938"},
}


def _sensor() -> ElectricityPriceSensor:
    sensor = ElectricityPriceSensor(MagicMock(), "system")
    sensor._prices = dict(REAL_PRICES)
    return sensor


@pytest.mark.parametrize(
    ("now", "key"),
    [
        (datetime(2026, 10, 20, 21, 22, 8, tzinfo=UTC), "2026-10-20T21:30Z"),
        # The slot ends at 21:30:00, from then on the next one is current
        (datetime(2026, 10, 20, 21, 29, 59, tzinfo=UTC), "2026-10-20T21:30Z"),
        (datetime(2026, 10, 20, 21, 30, 0, tzinfo=UTC), "2026-10-20T21:45Z"),
        (datetime(2026, 10, 20, 21, 15, 0, tzinfo=UTC), "2026-10-20T21:30Z"),
        # Across midnight
        (datetime(2026, 10, 20, 23, 50, 0, tzinfo=UTC), "2026-10-21T00:00Z"),
        # Home Assistant hands out local time; the key is UTC either way
        (
            datetime(2026, 10, 20, 23, 22, 8, tzinfo=ZoneInfo("Europe/Berlin")),
            "2026-10-20T21:30Z",
        ),
        (
            datetime(2026, 1, 20, 22, 22, 8, tzinfo=ZoneInfo("Europe/Berlin")),
            "2026-01-20T21:30Z",
        ),
    ],
)
def test_current_slot_key_is_the_end_of_the_slot_in_utc(now, key):
    with patch(NOW_PATH, return_value=now):
        assert current_slot_key() == key


def test_sensor_shows_the_price_the_app_shows():
    with patch(NOW_PATH, return_value=datetime(2026, 10, 20, 21, 22, 8, tzinfo=UTC)):
        # 39.1 ct/kWh in the app, not the 36.1 ct of an hour later
        assert _sensor().native_value == 0.3905


def test_sensor_switches_to_the_next_price_at_the_slot_boundary():
    sensor = _sensor()
    with patch(NOW_PATH, return_value=datetime(2026, 10, 20, 21, 29, 59, tzinfo=UTC)):
        assert sensor.native_value == 0.3905
    with patch(NOW_PATH, return_value=datetime(2026, 10, 20, 21, 30, 0, tzinfo=UTC)):
        assert sensor.native_value == 0.3875


def test_forecast_lists_the_start_of_the_following_slots():
    with patch(NOW_PATH, return_value=datetime(2026, 10, 20, 21, 22, 8, tzinfo=UTC)):
        forecast = _sensor().extra_state_attributes["forecast"]

    # The next slot is 21:30-21:45, stored under the key 21:45Z
    assert forecast[0] == {"datetime": "2026-10-20T21:30:00+00:00", "price": 0.3875}
    assert forecast[1] == {"datetime": "2026-10-20T21:45:00+00:00", "price": 0.3727}
    assert forecast[-1] == {"datetime": "2026-10-20T22:00:00+00:00", "price": 0.3606}
    assert len(forecast) == 3


def test_price_is_none_when_the_slot_is_missing():
    with patch(NOW_PATH, return_value=datetime(2026, 10, 21, 3, 0, 0, tzinfo=UTC)):
        assert _sensor().native_value is None
