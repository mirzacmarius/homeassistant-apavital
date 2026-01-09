"""Sensor platform for Apavital integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ApavitalDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class ApavitalSensorEntityDescription(SensorEntityDescription):
    """Describes Apavital sensor entity."""
    
    value_fn: Callable[[dict[str, Any]], Any]
    extra_attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSOR_DESCRIPTIONS: tuple[ApavitalSensorEntityDescription, ...] = (
    ApavitalSensorEntityDescription(
        key="water_index",
        translation_key="water_index",
        name="Water Index",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda data: data.get("index"),
        extra_attrs_fn=lambda data: {
            "total_readings": data.get("total_readings", 0),
            "average": data.get("average", 0),
            "median": data.get("median", 0),
        },
    ),
    ApavitalSensorEntityDescription(
        key="water_hourly",
        translation_key="water_hourly",
        name="Last Hour",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-pump",
        value_fn=lambda data: data.get("consumption_hourly"),
    ),
    ApavitalSensorEntityDescription(
        key="water_daily",
        translation_key="water_daily",
        name="Today",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:water",
        value_fn=lambda data: data.get("consumption_daily"),
    ),
    ApavitalSensorEntityDescription(
        key="water_weekly",
        translation_key="water_weekly",
        name="This Week",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:calendar-week",
        value_fn=lambda data: data.get("consumption_weekly"),
    ),
    ApavitalSensorEntityDescription(
        key="water_monthly",
        translation_key="water_monthly",
        name="This Month",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:calendar-month",
        value_fn=lambda data: data.get("consumption_monthly"),
    ),
    ApavitalSensorEntityDescription(
        key="leak_confidence",
        translation_key="leak_confidence",
        name="Leak Confidence",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda data: round(data.get("leak_confidence", 0) * 100, 1),
        extra_attrs_fn=lambda data: {
            "reason": data.get("leak_reason", ""),
            "consecutive_hours": data.get("leak_consecutive_hours", 0),
            "coefficient_of_variation": data.get("leak_cv"),
            "r_squared": data.get("leak_r_squared"),
            "night_consumption": data.get("leak_night_consumption", False),
            "average_hourly_flow": data.get("leak_avg_flow", 0),
        },
    ),
    ApavitalSensorEntityDescription(
        key="last_reading",
        translation_key="last_reading",
        name="Last Reading",
        icon="mdi:clock-outline",
        value_fn=lambda data: data.get("time"),
    ),
    ApavitalSensorEntityDescription(
        key="meter_serial",
        translation_key="meter_serial",
        name="Meter Serial",
        icon="mdi:identifier",
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.get("meter_serial"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Apavital sensors based on a config entry."""
    coordinator: ApavitalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities(
        ApavitalSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class ApavitalSensor(CoordinatorEntity[ApavitalDataUpdateCoordinator], SensorEntity):
    """Representation of an Apavital sensor."""
    
    _attr_has_entity_name = True
    entity_description: ApavitalSensorEntityDescription
    
    def __init__(
        self, 
        coordinator: ApavitalDataUpdateCoordinator, 
        entry: ConfigEntry,
        description: ApavitalSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Apavital Water Meter",
            "manufacturer": "Apavital",
            "model": "Smart Water Meter",
            "sw_version": "1.1.0",
        }
    
    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data:
            return self.entity_description.value_fn(self.coordinator.data)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if self.coordinator.data and self.entity_description.extra_attrs_fn:
            return self.entity_description.extra_attrs_fn(self.coordinator.data)
        return None
