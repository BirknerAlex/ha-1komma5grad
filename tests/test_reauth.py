"""Test the reauthentication flow and the auth failure handling."""

from typing import cast
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.einskomma5grad.api.error import (
    AuthenticationError,
    InvalidCredentialsError,
)

VALIDATE = "custom_components.einskomma5grad.config_flow.validate_input"


async def test_rejected_credentials_start_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, enable_custom_integrations
):
    """Rejected credentials end in a reauth flow instead of endless retries."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.einskomma5grad.api.systems.Systems.get_systems",
        side_effect=InvalidCredentialsError,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler("einskomma5grad")
    assert [f.get("context", {}).get("source") for f in flows] == ["reauth"]


async def test_reauth_flow_updates_password(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, enable_custom_integrations
):
    mock_config_entry.add_to_hass(hass)
    result = cast(dict, await mock_config_entry.start_reauth_flow(hass))
    assert result["step_id"] == "reauth_confirm"

    with (
        patch(VALIDATE, return_value={}),
        patch("homeassistant.config_entries.ConfigEntries.async_reload"),
    ):
        result = cast(
            dict,
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_PASSWORD: "new_password"}
            ),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new_password"
    assert mock_config_entry.data[CONF_USERNAME] == "test@example.com"


async def test_reauth_flow_invalid_auth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, enable_custom_integrations
):
    from custom_components.einskomma5grad.config_flow import InvalidAuth

    mock_config_entry.add_to_hass(hass)
    result = cast(dict, await mock_config_entry.start_reauth_flow(hass))

    with patch(VALIDATE, side_effect=InvalidAuth):
        result = cast(
            dict,
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_PASSWORD: "still_wrong"}
            ),
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PASSWORD] == "test_password"


async def test_reauth_flow_cannot_connect(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, enable_custom_integrations
):
    """A network failure is not reported as a wrong password."""
    mock_config_entry.add_to_hass(hass)
    result = cast(dict, await mock_config_entry.start_reauth_flow(hass))

    with patch(
        "custom_components.einskomma5grad.config_flow.Client.get_user",
        side_effect=AuthenticationError("Login failed due to network error"),
    ):
        result = cast(
            dict,
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_PASSWORD: "new_password"}
            ),
        )

    assert result["errors"] == {"base": "cannot_connect"}
