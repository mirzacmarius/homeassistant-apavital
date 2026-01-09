"""Diagnostics support for Apavital integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_CODE, CONF_JWT_TOKEN, DOMAIN
from .coordinator import ApavitalDataUpdateCoordinator

TO_REDACT = {CONF_JWT_TOKEN, CONF_CLIENT_CODE, "meter_serial"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ApavitalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    return {
        "config_entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": coordinator.diagnostics_data,
        "data": async_redact_data(coordinator.data or {}, TO_REDACT) if coordinator.data else None,
    }
