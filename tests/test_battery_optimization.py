"""Tests for the battery decisions planned by Heartbeat AI."""

import datetime
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.einskomma5grad.api.error import RequestError
from custom_components.einskomma5grad.api.optimizations import (
    active_window,
    battery_hold_active,
    parse_windows,
    upcoming_windows,
)
from custom_components.einskomma5grad.const import DOMAIN
from tests.conftest import SYSTEM_SLUG, load_mock

BINARY_SENSOR = f"binary_sensor.battery_no_discharge_active_{SYSTEM_SLUG}"
FETCH = "custom_components.einskomma5grad.coordinator.fetch_optimizations"


def _utc(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event(decision: str, asset: str, start: datetime.datetime, end: datetime.datetime):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "timestamp": start.isoformat(),
        "data": {
            "decision": decision,
            "asset": asset,
            "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "marketPrice": {"value": 0.07, "currency": "EUR"},
            "stateOfCharge": 50,
        },
    }


async def _setup(hass, mock_config_entry, mock_api, events=None):
    if events is not None:
        mock_api["data"]["optimizations"] = {"events": events}
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][mock_config_entry.entry_id].coordinator


def test_parse_windows_from_mock():
    windows = parse_windows(load_mock("GET_heartbeat-ai_optimizations.json"))

    assert [w.decision for w in windows] == [
        "BATTERY_NO_DISCHARGE",
        "HEATPUMP_AUTO",
        "BATTERY_CHARGE_FROM_GRID",
    ]
    assert windows[0].market_price == 0.071
    assert windows[0].state_of_charge == 54


def test_parse_windows_skips_malformed_events():
    windows = parse_windows(
        {
            "events": [
                {"data": {"decision": "BATTERY_NO_DISCHARGE", "asset": "BATTERY"}},
                {
                    "data": {
                        "decision": "X",
                        "asset": "BATTERY",
                        "from": "nope",
                        "to": "nope",
                    }
                },
                {
                    "data": {
                        "decision": "X",
                        "asset": "BATTERY",
                        "from": "2026-10-21T02:00:00Z",
                        "to": "2026-10-21T01:00:00Z",
                    }
                },
                "junk",
                {"data": None},
            ]
        }
    )
    assert windows == []
    assert parse_windows(None) == []
    assert parse_windows({"events": None}) == []


def test_hold_is_active_inside_battery_windows_only():
    windows = parse_windows(load_mock("GET_heartbeat-ai_optimizations.json"))

    assert battery_hold_active(windows, _utc("2026-10-21T00:30:00Z"))
    assert battery_hold_active(windows, _utc("2026-10-21T02:30:00Z"))
    # The end of a window is exclusive, and the heat pump window does not count.
    assert not battery_hold_active(windows, _utc("2026-10-21T03:00:00Z"))
    assert not battery_hold_active(windows, _utc("2026-10-20T22:59:59Z"))

    active = active_window(windows, _utc("2026-10-21T02:30:00Z"))
    assert active is not None
    assert active.decision == "BATTERY_CHARGE_FROM_GRID"
    assert [
        w.decision for w in upcoming_windows(windows, _utc("2026-10-21T00:30:00Z"))
    ] == ["BATTERY_CHARGE_FROM_GRID"]


def test_unknown_decision_is_not_treated_as_hold():
    now = dt_util.utcnow()
    windows = parse_windows(
        {
            "events": [
                _event(
                    "BATTERY_SOMETHING_NEW",
                    "BATTERY",
                    now - timedelta(hours=1),
                    now + timedelta(hours=1),
                )
            ]
        }
    )
    assert not battery_hold_active(windows, now)
    assert active_window(windows, now) is not None


async def test_sensor_reflects_active_hold_window(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    now = dt_util.utcnow()
    await _setup(
        hass,
        mock_config_entry,
        mock_api,
        [
            _event(
                "BATTERY_NO_DISCHARGE",
                "BATTERY",
                now - timedelta(hours=1),
                now + timedelta(hours=1),
            ),
            _event(
                "BATTERY_CHARGE_FROM_GRID",
                "BATTERY",
                now + timedelta(hours=3),
                now + timedelta(hours=4),
            ),
        ],
    )

    binary = hass.states.get(BINARY_SENSOR)
    assert binary is not None
    assert binary.state == "on"
    assert binary.attributes["decision"] == "BATTERY_NO_DISCHARGE"
    assert binary.attributes["market_price"] == 0.07
    assert [w["decision"] for w in binary.attributes["upcoming"]] == [
        "BATTERY_CHARGE_FROM_GRID"
    ]


async def test_sensor_off_without_active_battery_window(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    now = dt_util.utcnow()
    await _setup(
        hass,
        mock_config_entry,
        mock_api,
        [
            _event(
                "HEATPUMP_AUTO",
                "HEATPUMP",
                now - timedelta(hours=1),
                now + timedelta(hours=1),
            )
        ],
    )

    binary = hass.states.get(BINARY_SENSOR)
    assert binary is not None
    assert binary.state == "off"
    assert binary.attributes["decision"] is None
    assert binary.attributes["upcoming"] == []


async def test_failing_endpoint_makes_only_this_entity_unavailable(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    with patch(FETCH, side_effect=RequestError("404")):
        coordinator = await _setup(hass, mock_config_entry, mock_api)

    assert coordinator.last_update_success
    state = hass.states.get(BINARY_SENSOR)
    assert state is not None
    assert state.state == "unavailable"


async def test_optimizations_fetched_once_per_interval(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    with patch(FETCH, return_value={"events": []}) as call:
        coordinator = await _setup(hass, mock_config_entry, mock_api)
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    assert call.call_count == 1
