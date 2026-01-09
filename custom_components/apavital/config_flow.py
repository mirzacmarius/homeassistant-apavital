"""Config flow for Apavital integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import API_URL, CONF_CLIENT_CODE, CONF_JWT_TOKEN, DOMAIN

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


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""
