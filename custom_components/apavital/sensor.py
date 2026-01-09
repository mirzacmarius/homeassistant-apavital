"""Sensor platform for Apavital integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
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
    """Set up Apavital sensors based on a config entry."""
    coordinator: ApavitalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([
        ApavitalWaterIndexSensor(coordinator, entry),
        ApavitalWaterDailySensor(coordinator, entry),
        ApavitalLastUpdateSensor(coordinator, entry),
        ApavitalMeterSerialSensor(coordinator, entry),
    ])


class ApavitalBaseSensor(CoordinatorEntity[ApavitalDataUpdateCoordinator], SensorEntity):
    """Base class for Apavital sensors."""
    
    _attr_has_entity_name = True
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Apavital Water Meter",
            "manufacturer": "Apavital",
            "model": "Smart Water Meter",
        }


class ApavitalWaterIndexSensor(ApavitalBaseSensor):
    """Sensor for water meter index (total consumption)."""
    
    _attr_name = "Water Index"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_index"
    
    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("index")
        return None


class ApavitalWaterDailySensor(ApavitalBaseSensor):
    """Sensor for daily water consumption."""
    
    _attr_name = "Water Daily Consumption"
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:water"
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_daily"
    
    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("consumption_daily")
        return None


class ApavitalLastUpdateSensor(ApavitalBaseSensor):
    """Sensor for last update time."""
    
    _attr_name = "Last Reading"
    _attr_icon = "mdi:clock-outline"
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_update"
    
    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("time")
        return None


class ApavitalMeterSerialSensor(ApavitalBaseSensor):
    """Sensor for meter serial number."""
    
    _attr_name = "Meter Serial"
    _attr_icon = "mdi:identifier"
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_meter_serial"
    
    @property
    def native_value(self) -> str | None:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.coordinator.data.get("meter_serial")
        return None
