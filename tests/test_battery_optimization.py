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
    merge_windows,
    parse_windows,
    upcoming_windows,
)
from custom_components.einskomma5grad.const import DOMAIN
from tests.conftest import SYSTEM_SLUG, load_mock

BINARY_SENSOR = f"binary_sensor.battery_no_discharge_active_{SYSTEM_SLUG}"
FETCH = "custom_components.einskomma5grad.coordinator.fetch_optimizations"
TRACK_TIME = (
    "custom_components.einskomma5grad.binary_sensor.async_track_point_in_utc_time"
)

SLOT = timedelta(minutes=15)
BASE = datetime.datetime(2026, 10, 20, 20, 0, tzinfo=datetime.UTC)


def _event(
    decision: str,
    asset: str,
    start: datetime.datetime,
    end: datetime.datetime | None = None,
    price: float | None = 40.0,
    soc: int | None = None,
):
    """A 15-minute slot as the API sends it: same id everywhere, price in EUR/MWh."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "timestamp": start.isoformat(),
        "data": {
            "decision": decision,
            "asset": asset,
            "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": (end or start + SLOT).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "marketPrice": {"value": price, "currency": "EUR"},
            "energySold": None,
            "energyBought": None,
            "totalCost": None,
            "stateOfCharge": soc,
        },
    }


def _slots(decision: str, start: datetime.datetime, count: int, asset="BATTERY"):
    return [_event(decision, asset, start + i * SLOT) for i in range(count)]


async def _setup(hass, mock_config_entry, mock_api, events=None):
    if events is not None:
        mock_api["data"]["optimizations"] = {"events": events}
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][mock_config_entry.entry_id].coordinator


def test_mock_fixture_parses():
    windows = parse_windows(load_mock("GET_heartbeat-ai_optimizations.json"))

    assert windows
    assert all(w.end > w.start for w in windows)
    assert windows == sorted(windows, key=lambda w: w.start)


def test_market_price_is_converted_to_eur_per_kwh():
    windows = parse_windows(
        {"events": [_event("BATTERY_NO_DISCHARGE", "BATTERY", BASE, price=36.94)]}
    )
    assert windows[0].market_price == 0.03694

    missing = parse_windows(
        {"events": [_event("BATTERY_NO_DISCHARGE", "BATTERY", BASE, price=None)]}
    )
    assert missing[0].market_price is None


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


def test_null_state_of_charge_and_log_are_tolerated():
    event = _event("BATTERY_NO_DISCHARGE", "BATTERY", BASE, soc=None)
    event["data"]["log"] = ["2026-10-20T20:00:04Z"]
    windows = parse_windows({"events": [event]})
    assert windows[0].state_of_charge is None


def test_merge_joins_adjacent_slots_of_the_same_decision():
    windows = parse_windows(
        {
            "events": [
                *_slots("BATTERY_NO_DISCHARGE", BASE, 4),
                *_slots("BATTERY_CHARGE_FROM_GRID", BASE + 4 * SLOT, 2),
                # Same decision again after a gap: a separate window
                *_slots("BATTERY_NO_DISCHARGE", BASE + 8 * SLOT, 1),
                # Heat pump slots overlap but belong to another asset
                *_slots("HEATPUMP_AUTO", BASE, 3, asset="HEATPUMP"),
            ]
        }
    )
    merged = merge_windows(windows)
    battery = [w for w in merged if w.asset == "BATTERY"]

    assert [(w.decision, w.start, w.end) for w in battery] == [
        ("BATTERY_NO_DISCHARGE", BASE, BASE + 4 * SLOT),
        ("BATTERY_CHARGE_FROM_GRID", BASE + 4 * SLOT, BASE + 6 * SLOT),
        ("BATTERY_NO_DISCHARGE", BASE + 8 * SLOT, BASE + 9 * SLOT),
    ]
    heat_pump = [w for w in merged if w.asset == "HEATPUMP"]
    assert [(w.start, w.end) for w in heat_pump] == [(BASE, BASE + 3 * SLOT)]


def test_merge_averages_the_market_price():
    windows = parse_windows(
        {
            "events": [
                _event("BATTERY_NO_DISCHARGE", "BATTERY", BASE, price=30.0),
                _event("BATTERY_NO_DISCHARGE", "BATTERY", BASE + SLOT, price=40.0),
                _event("BATTERY_NO_DISCHARGE", "BATTERY", BASE + 2 * SLOT, price=None),
            ]
        }
    )
    (merged,) = merge_windows(windows)
    assert merged.market_price == 0.035


def test_merge_tolerates_duplicate_slots():
    windows = parse_windows({"events": _slots("BATTERY_NO_DISCHARGE", BASE, 2) * 2})
    merged = merge_windows(windows)
    assert [(w.start, w.end) for w in merged] == [(BASE, BASE + 2 * SLOT)]


def test_hold_is_active_inside_battery_windows_only():
    windows = parse_windows(
        {
            "events": [
                *_slots("BATTERY_NO_DISCHARGE", BASE, 2),
                *_slots("BATTERY_CHARGE_FROM_GRID", BASE + 2 * SLOT, 1),
                *_slots("HEATPUMP_AUTO", BASE + 3 * SLOT, 2, asset="HEATPUMP"),
            ]
        }
    )

    assert battery_hold_active(windows, BASE)
    assert battery_hold_active(windows, BASE + 2 * SLOT + timedelta(minutes=5))
    # The end is exclusive, and the heat pump window does not count.
    assert not battery_hold_active(windows, BASE + 3 * SLOT)
    assert not battery_hold_active(windows, BASE - timedelta(seconds=1))

    active = active_window(windows, BASE + 2 * SLOT)
    assert active is not None
    assert active.decision == "BATTERY_CHARGE_FROM_GRID"
    assert [w.decision for w in upcoming_windows(windows, BASE + SLOT)] == [
        "BATTERY_CHARGE_FROM_GRID"
    ]


def test_unknown_decision_is_not_treated_as_hold():
    windows = parse_windows(
        {"events": [_event("BATTERY_SOMETHING_NEW", "BATTERY", BASE)]}
    )
    assert not battery_hold_active(windows, BASE)
    assert active_window(windows, BASE) is not None


async def test_sensor_reflects_merged_hold_window(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    now = dt_util.utcnow()
    current = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 15)
    events = [
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current - SLOT, price=40.0),
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current, price=36.94),
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current + SLOT, price=30.0),
        *_slots("BATTERY_CHARGE_FROM_GRID", current + 3 * SLOT, 2),
    ]
    await _setup(hass, mock_config_entry, mock_api, events)

    binary = hass.states.get(BINARY_SENSOR)
    assert binary is not None
    assert binary.state == "on"
    assert binary.attributes["decision"] == "BATTERY_NO_DISCHARGE"
    # Merged window, but the price of the current slot
    assert binary.attributes["window_start"] == (current - SLOT).isoformat()
    assert binary.attributes["window_end"] == (current + 2 * SLOT).isoformat()
    assert binary.attributes["market_price"] == 0.03694
    assert binary.attributes["upcoming"] == [
        {
            "decision": "BATTERY_CHARGE_FROM_GRID",
            "from": (current + 3 * SLOT).isoformat(),
            "to": (current + 5 * SLOT).isoformat(),
            "market_price": 0.04,
        }
    ]


async def test_updates_are_scheduled_at_slot_boundaries_inside_merged_window(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    """The price changes per slot, so each slot boundary needs an update."""
    now = dt_util.utcnow()
    current = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 15)
    events = [
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current, price=36.94),
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current + SLOT, price=30.0),
        _event("BATTERY_NO_DISCHARGE", "BATTERY", current + 2 * SLOT, price=32.0),
    ]
    with patch(TRACK_TIME) as track:
        await _setup(hass, mock_config_entry, mock_api, events)

    assert track.call_args_list
    # The merged window ends at current + 3 slots, but the next update is due
    # when the next slot starts.
    assert {call.args[2] for call in track.call_args_list} == {current + SLOT}


async def test_sensor_off_without_active_battery_window(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    now = dt_util.utcnow()
    await _setup(
        hass,
        mock_config_entry,
        mock_api,
        [_event("HEATPUMP_AUTO", "HEATPUMP", now - SLOT, now + SLOT)],
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
