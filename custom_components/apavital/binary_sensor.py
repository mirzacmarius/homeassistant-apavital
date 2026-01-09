"""Binary sensor platform for Apavital integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ApavitalDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Apavital binary sensors based on a config entry."""
    coordinator: ApavitalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([
        ApavitalLeakSensor(coordinator, entry),
    ])


class ApavitalLeakSensor(CoordinatorEntity[ApavitalDataUpdateCoordinator], BinarySensorEntity):
    """Binary sensor for water leak detection."""
    
    _attr_has_entity_name = True
    _attr_name = "Leak Detected"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:pipe-leak"
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_leak_detected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Apavital Water Meter",
            "manufacturer": "Apavital",
            "model": "Smart Water Meter",
        }
    
    @property
    def is_on(self) -> bool | None:
        """Return true if leak is detected."""
        if self.coordinator.data:
            return self.coordinator.data.get("leak_detected", False)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        """Return extra state attributes."""
        if self.coordinator.data:
            return {
                "hourly_consumption": self.coordinator.data.get("consumption_hourly", 0),
                "threshold": self.coordinator.leak_threshold,
            }
        return {}
