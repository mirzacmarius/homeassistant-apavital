"""Config flow for Apavital integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    API_URL,
    CONF_CLIENT_CODE,
    CONF_JWT_TOKEN,
    CONF_LEAK_THRESHOLD,
    CONF_SCAN_INTERVAL,
    DEFAULT_LEAK_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_CODE): str,
        vol.Required(CONF_JWT_TOKEN): str,
    }
)


async def validate_input(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {data[CONF_JWT_TOKEN]}"}
        form_data = aiohttp.FormData()
        form_data.add_field("clientCode", data[CONF_CLIENT_CODE])
        form_data.add_field("ctrAdmin", "false")
        form_data.add_field("ctrEmail", "")
        
        async with session.post(
            API_URL, 
            headers=headers, 
            data=form_data,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status == 401:
                raise InvalidAuth
            
            response.raise_for_status()
            result = await response.json()
            
            # Check if we got valid data
            if "data" not in result:
                raise CannotConnect
            
            return {"title": f"Apavital ({data[CONF_CLIENT_CODE]})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Apavital."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            try:
                info = await validate_input(user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Check if already configured
                await self.async_set_unique_id(user_input[CONF_CLIENT_CODE])
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "client_code_help": "GRUPMAS_COD from your Apavital account",
                "jwt_token_help": "JWT token from browser Developer Tools",
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle reauthorization when token expires."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauthorization confirmation."""
        errors: dict[str, str] = {}
        
        reauth_entry = self._get_reauth_entry()
        
        if user_input is not None:
            try:
                # Validate the new token
                test_data = {
                    CONF_CLIENT_CODE: reauth_entry.data[CONF_CLIENT_CODE],
                    CONF_JWT_TOKEN: user_input[CONF_JWT_TOKEN],
                }
                await validate_input(test_data)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Update the config entry with new token
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_JWT_TOKEN: user_input[CONF_JWT_TOKEN],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_JWT_TOKEN): str,
            }),
            errors=errors,
            description_placeholders={
                "client_code": reauth_entry.data[CONF_CLIENT_CODE],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Apavital."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # If token is provided, validate it
            if user_input.get(CONF_JWT_TOKEN):
                try:
                    test_data = {
                        CONF_CLIENT_CODE: self.config_entry.data[CONF_CLIENT_CODE],
                        CONF_JWT_TOKEN: user_input[CONF_JWT_TOKEN],
                    }
                    await validate_input(test_data)
                    
                    # Update main data with new token
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={
                            **self.config_entry.data,
                            CONF_JWT_TOKEN: user_input[CONF_JWT_TOKEN],
                        },
                    )
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
            
            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        CONF_LEAK_THRESHOLD: user_input.get(CONF_LEAK_THRESHOLD, DEFAULT_LEAK_THRESHOLD),
                    },
                )

        # Get current values
        current_scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_leak_threshold = self.config_entry.options.get(
            CONF_LEAK_THRESHOLD, DEFAULT_LEAK_THRESHOLD
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_JWT_TOKEN,
                    description={"suggested_value": ""},
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current_scan_interval,
                ): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
                vol.Optional(
                    CONF_LEAK_THRESHOLD,
                    default=current_leak_threshold,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=1.0)),
            }),
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
