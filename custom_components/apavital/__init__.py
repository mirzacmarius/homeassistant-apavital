"""Apavital Water Integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN, SERVICE_REFRESH
from .coordinator import ApavitalDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

SCAN_INTERVAL = timedelta(hours=1)

SERVICE_REFRESH_SCHEMA = vol.Schema({
    vol.Optional("entry_id"): cv.string,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Apavital from a config entry."""
    coordinator = ApavitalDataUpdateCoordinator(hass, entry)
    
    await coordinator.async_config_entry_first_refresh()
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        async def handle_refresh(call: ServiceCall) -> None:
            """Handle the refresh service call."""
            entry_id = call.data.get("entry_id")
            
            if entry_id:
                # Refresh specific entry
                if entry_id in hass.data[DOMAIN]:
                    await hass.data[DOMAIN][entry_id].async_request_refresh()
            else:
                # Refresh all entries
                for coordinator in hass.data[DOMAIN].values():
                    await coordinator.async_request_refresh()
        
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            handle_refresh,
            schema=SERVICE_REFRESH_SCHEMA,
        )
    
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        
        # Unregister services if no more entries
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
