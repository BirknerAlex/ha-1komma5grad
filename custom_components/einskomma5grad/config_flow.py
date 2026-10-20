"""Config flow for 1KOMMA5GRAD integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import requests
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api.client import Client
from .api.error import ApiError, InvalidCredentialsError
from .const import (
    CONF_ERROR_REPORTING,
    DEFAULT_ERROR_REPORTING,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    api_client = Client(data[CONF_USERNAME], data[CONF_PASSWORD])

    try:
        return await hass.async_add_executor_job(lambda: api_client.get_user())
    except InvalidCredentialsError as e:
        raise InvalidAuth(e.message) from e
    except (ApiError, requests.RequestException) as e:
        # Network errors and unexpected responses are wrapped in ApiError by the client.
        raise CannotConnect from e
    finally:
        await hass.async_add_executor_job(lambda: api_client.close)


class HeartbeatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 1KOMMA5GRAD."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Save username/password as data and store scan interval in options
                options = {
                    CONF_SCAN_INTERVAL: int(
                        user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                    ),
                    CONF_ERROR_REPORTING: DEFAULT_ERROR_REPORTING,
                }
                return self.async_create_entry(
                    title=user["firstName"] + " " + user["lastName"],
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options=options,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a reauthentication after the stored credentials were rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new password."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_USERNAME: reauth_entry.data[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates=data
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": reauth_entry.data[CONF_USERNAME]},
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler for this config entry."""
        _LOGGER.debug(
            "ConfigFlow.async_get_options_flow called for %s",
            getattr(config_entry, "entry_id", config_entry),
        )
        return OptionsFlowHandler(config_entry)


# Also provide a module-level factory for older/newer HA compatibility
def async_get_options_flow(config_entry):
    """Module-level factory for options flow (compatibility layer)."""
    _LOGGER.debug(
        "module-level async_get_options_flow called for %s",
        getattr(config_entry, "entry_id", config_entry),
    )
    return OptionsFlowHandler(config_entry)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for the integration."""

    def __init__(self, config_entry):
        _LOGGER.debug(
            "OptionsFlowHandler init for config_entry %s",
            getattr(config_entry, "entry_id", config_entry),
        )
        # Use a private attribute because the base class exposes config_entry as a
        # read-only property in some HA versions.
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage the options for the integration."""
        errors: dict[str, str] = {}

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                ),
                vol.Optional(
                    CONF_ERROR_REPORTING,
                    default=self._config_entry.options.get(
                        CONF_ERROR_REPORTING, DEFAULT_ERROR_REPORTING
                    ),
                ): bool,
            }
        )

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init", data_schema=data_schema, errors=errors
        )
