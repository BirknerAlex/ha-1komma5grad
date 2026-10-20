"""Test the Smart Charge settings of an EV: current SoC, target SoC, departure time."""

import logging
from typing import cast

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .conftest import EV_ID, SYSTEM_ID

CURRENT_SOC = f"einskomma5grad_ev_current_soc_{SYSTEM_ID}_{EV_ID}"
TARGET_SOC = f"einskomma5grad_ev_target_soc_{SYSTEM_ID}_{EV_ID}"
DEPARTURE_TIME = f"einskomma5grad_ev_departure_time_{SYSTEM_ID}_{EV_ID}"


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, "einskomma5grad", unique_id
    )
    assert entity_id is not None
    return entity_id


def _last_patch_body(mock_api) -> dict:
    return mock_api["client"].patch.call_args.kwargs["json"]


async def _setup(hass: HomeAssistant, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_current_soc_settable_in_smart_charge_without_stored_soc(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    """In SMART_CHARGE the SoC can be entered even if the API has none yet."""
    ev = cast(list, mock_api["data"]["ev_chargers"])[0]
    ev["chargingMode"] = "SMART_CHARGE"
    del ev["manualSoc"]
    await _setup(hass, mock_config_entry)

    entity_id = _entity_id(hass, "number", CURRENT_SOC)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "unknown"

    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 42}, blocking=True
    )

    assert _last_patch_body(mock_api)["manualSoc"] == 0.42
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 42.0


async def test_current_soc_unavailable_outside_smart_charge(
    hass: HomeAssistant, setup_integration
):
    """The mock EV is in QUICK_CHARGE, where the SoC is not used."""
    state = hass.states.get(_entity_id(hass, "number", CURRENT_SOC))
    assert state is not None
    assert state.state == "unavailable"


async def test_target_soc_read_and_set(
    hass: HomeAssistant, setup_integration, mock_api
):
    """The target SoC is shown in percent and sent as a fraction."""
    entity_id = _entity_id(hass, "number", TARGET_SOC)
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 59.0

    await hass.services.async_call(
        "number", "set_value", {"entity_id": entity_id, "value": 80}, blocking=True
    )

    body = _last_patch_body(mock_api)
    assert body["targetSoc"] == 0.8
    assert body["departureTime"] == "08:00"
    assert body["chargingMode"] == "QUICK_CHARGE"
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 80.0


async def test_departure_time_read_and_set(
    hass: HomeAssistant, setup_integration, mock_api
):
    """The departure time is shown as a time and sent as HH:MM."""
    entity_id = _entity_id(hass, "time", DEPARTURE_TIME)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "08:00:00"

    await hass.services.async_call(
        "time", "set_value", {"entity_id": entity_id, "time": "06:30:00"}, blocking=True
    )

    body = _last_patch_body(mock_api)
    assert body["departureTime"] == "06:30"
    assert body["targetSoc"] == 0.59
    assert body["chargingMode"] == "QUICK_CHARGE"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "06:30:00"


async def test_schedule_entities_unavailable_without_api_values(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    """An EV without schedule settings does not break the setup."""
    ev = cast(list, mock_api["data"]["ev_chargers"])[0]
    del ev["targetSoc"]
    del ev["departureTime"]
    await _setup(hass, mock_config_entry)

    for domain, unique_id in (("number", TARGET_SOC), ("time", DEPARTURE_TIME)):
        state = hass.states.get(_entity_id(hass, domain, unique_id))
        assert state is not None
        assert state.state == "unavailable"


async def test_assets_linked_to_gateway_without_deprecated_via_device(
    hass: HomeAssistant, setup_integration, caplog
):
    """Assets hang off the gateway, and the deprecated `via_device` is not used."""
    devices = {
        identifier: device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), setup_integration.entry_id
        )
        for domain, identifier in device.identifiers
        if domain == "einskomma5grad"
    }
    gateway = devices["I032-002-000-000-068-P-X"]

    assert gateway.via_device_id is None
    for serial in ("SN-HY-000001", "SN-EV-000001", "SN-HP-000001"):
        assert devices[serial].via_device_id == gateway.id

    # The integration is set up by the fixture, i.e. in the setup phase.
    assert not [
        record
        for record in caplog.get_records("setup")
        if record.levelno >= logging.WARNING and "via_device" in record.getMessage()
    ]


async def test_asset_with_the_gateway_serial_does_not_break_setup(
    hass: HomeAssistant, mock_config_entry, mock_api, enable_custom_integrations
):
    """An asset resolving to the gateway device must not be linked to itself."""
    assets = cast(dict, mock_api["data"]["status_and_assets"])["assets"]
    assets[0]["serialnumber"] = "I032-002-000-000-068-P-X"
    await _setup(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
