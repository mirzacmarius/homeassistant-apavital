"""Binary sensor platform for Apavital integration."""
from __future__ import annotations

from typing import Any

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
    """Binary sensor for water leak detection using pattern analysis.
    
    This sensor uses multiple factors to detect leaks:
    - Consecutive hours with non-zero consumption
    - Coefficient of variation (low = constant flow = leak)
    - R² score (high linearity = constant flow = leak)
    - Night-time consumption (very suspicious)
    - Average hourly flow rate
    """
    
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
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes with detailed leak analysis."""
        if not self.coordinator.data:
            return {}
        
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            # Basic info
            "hourly_consumption": data.get("consumption_hourly", 0),
            "threshold": self.coordinator.leak_threshold,
            # Leak analysis results
            "confidence": data.get("leak_confidence", 0),
            "reason": data.get("leak_reason", ""),
            # Individual factors
            "consecutive_hours": data.get("leak_consecutive_hours", 0),
            "coefficient_of_variation": data.get("leak_cv"),
            "r_squared": data.get("leak_r_squared"),
            "night_consumption": data.get("leak_night_consumption", False),
            "average_hourly_flow": data.get("leak_avg_flow", 0),
        }
        
        # Add detailed factors if available (for debugging/advanced users)
        factors = data.get("leak_factors", {})
        if factors:
            attrs["analysis_factors"] = factors
        
        return attrs
