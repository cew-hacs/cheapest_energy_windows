"""Sensor platform for Cheapest Energy Windows."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .calculation_engine import WindowCalculationEngine
from .const import (
    DOMAIN,
    LOGGER_NAME,
    PREFIX,
    STATE_CHARGE,
    STATE_DISCHARGE,
    STATE_DISCHARGE_AGGRESSIVE,
    STATE_IDLE,
    STATE_OFF,
    STATE_AVAILABLE,
    STATE_UNAVAILABLE,
    ATTR_CHEAPEST_TIMES,
    ATTR_CHEAPEST_PRICES,
    ATTR_EXPENSIVE_TIMES,
    ATTR_EXPENSIVE_PRICES,
    ATTR_EXPENSIVE_TIMES_AGGRESSIVE,
    ATTR_EXPENSIVE_PRICES_AGGRESSIVE,
    ATTR_ACTUAL_CHARGE_TIMES,
    ATTR_ACTUAL_CHARGE_PRICES,
    ATTR_ACTUAL_DISCHARGE_TIMES,
    ATTR_ACTUAL_DISCHARGE_PRICES,
    ATTR_COMPLETED_CHARGE_WINDOWS,
    ATTR_COMPLETED_DISCHARGE_WINDOWS,
    ATTR_COMPLETED_CHARGE_COST,
    ATTR_COMPLETED_DISCHARGE_REVENUE,
    ATTR_NUM_WINDOWS,
    ATTR_MIN_SPREAD_REQUIRED,
    ATTR_SPREAD_PERCENTAGE,
    ATTR_SPREAD_MET,
    ATTR_SPREAD_AVG,
    ATTR_ACTUAL_SPREAD_AVG,
    ATTR_DISCHARGE_SPREAD_MET,
    ATTR_AGGRESSIVE_DISCHARGE_SPREAD_MET,
    ATTR_AVG_CHEAP_PRICE,
    ATTR_AVG_EXPENSIVE_PRICE,
    ATTR_CURRENT_PRICE,
    ATTR_PRICE_OVERRIDE_ACTIVE,
    ATTR_TIME_OVERRIDE_ACTIVE,
)
from .coordinator import CEWCoordinator

_LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Cheapest Energy Windows sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    sensors = [
        CEWTodaySensor(coordinator, config_entry),
        CEWTomorrowSensor(coordinator, config_entry),
    ]

    async_add_entities(sensors)


class CEWBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for CEW sensors."""

    def __init__(
        self,
        coordinator: CEWCoordinator,
        config_entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._sensor_type = sensor_type

        # Set unique ID and name
        self._attr_unique_id = f"{PREFIX}{sensor_type}"
        self._attr_name = f"CEW {sensor_type.replace('_', ' ').title()}"
        self._attr_has_entity_name = False

        # Initialize state
        self._attr_native_value = STATE_OFF

        # Track previous values to detect changes
        self._previous_state = None
        self._previous_attributes = None

        # Persist automation_enabled across sensor recreations (integration reloads)
        # This allows us to detect actual changes in automation state
        persistent_key = f"{DOMAIN}_{config_entry.entry_id}_sensor_{sensor_type}_state"
        if persistent_key not in coordinator.hass.data:
            coordinator.hass.data[persistent_key] = {
                "previous_automation_enabled": None,
                "previous_calc_config_hash": None,
            }
        self._persistent_sensor_state = coordinator.hass.data[persistent_key]
        self._previous_automation_enabled = self._persistent_sensor_state["previous_automation_enabled"]
        self._previous_calc_config_hash = self._persistent_sensor_state["previous_calc_config_hash"]

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": "Cheapest Energy Windows",
            "manufacturer": "Community",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }

    def _calc_config_hash(self, config: Dict[str, Any], is_tomorrow: bool = False) -> str:
        """Create a hash of config values that affect calculations.

        Only includes values that impact window calculations and current state.
        Excludes notification settings and other non-calculation config.
        """
        suffix = "_tomorrow" if is_tomorrow and config.get("tomorrow_settings_enabled", False) else ""

        # Config values that affect calculations
        calc_values = [
            config.get("automation_enabled", True),
            config.get(f"charging_windows{suffix}", 4),
            config.get(f"expensive_windows{suffix}", 4),
            config.get(f"cheap_percentile{suffix}", 25),
            config.get(f"expensive_percentile{suffix}", 25),
            config.get(f"min_spread{suffix}", 10),
            config.get(f"min_spread_discharge{suffix}", 20),
            config.get(f"aggressive_discharge_spread{suffix}", 40),
            config.get(f"min_price_difference{suffix}", 0.05),
            config.get("vat", 0.21),
            config.get("tax", 0.12286),
            config.get("additional_cost", 0.02398),
            config.get("battery_rte", 90),
            config.get("charge_power", 2400),
            config.get("discharge_power", 2400),
            config.get(f"price_override_enabled{suffix}", False),
            config.get(f"price_override_threshold{suffix}", 0.15),
            config.get("pricing_window_duration", "15_minutes"),
            # Calculation window settings affect what windows are selected
            config.get("calculation_window_enabled", False),
            config.get("calculation_window_start", "00:00:00"),
            config.get("calculation_window_end", "23:59:59"),
        ]

        # Add time overrides (these affect current state)
        for i in range(1, 4):
            calc_values.extend([
                config.get(f"time_override_{i}_enabled{suffix}", False),
                config.get(f"time_override_{i}_start{suffix}", "00:00:00"),
                config.get(f"time_override_{i}_end{suffix}", "00:00:00"),
                config.get(f"time_override_{i}_mode{suffix}", "charge"),
            ])

        # Create hash from all values
        return str(hash(tuple(str(v) for v in calc_values)))


class CEWTodaySensor(CEWBaseSensor):
    """Sensor for today's energy windows."""

    def __init__(self, coordinator: CEWCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize today sensor."""
        super().__init__(coordinator, config_entry, "today")
        self._calculation_engine = WindowCalculationEngine()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("-"*60)
        _LOGGER.debug(f"SENSOR UPDATE: {self._sensor_type}")
        _LOGGER.debug(f"Coordinator data exists: {self.coordinator.data is not None}")

        if not self.coordinator.data:
            # No coordinator data - maintain previous state if we have one
            # This prevents brief unavailable states during updates
            if self._previous_state is not None:
                _LOGGER.debug("No coordinator data, maintaining previous state")
                # Use previous values and skip write - sensor already has correct state
                return
            else:
                _LOGGER.debug("No coordinator data and no previous state, defaulting to OFF")
                new_state = STATE_OFF
                new_attributes = {}
                self._attr_native_value = new_state
                self._attr_extra_state_attributes = new_attributes
                self._previous_state = new_state
                self._previous_attributes = new_attributes.copy() if new_attributes else None
                self.async_write_ha_state()
                return

        # Layer 3: Check what changed
        price_data_changed = self.coordinator.data.get("price_data_changed", True)
        config_changed = self.coordinator.data.get("config_changed", False)
        is_first_load = self.coordinator.data.get("is_first_load", False)
        scheduled_update = self.coordinator.data.get("scheduled_update", False)

        config = self.coordinator.data.get("config", {})
        current_automation_enabled = config.get("automation_enabled", True)

        # Check if calculation-affecting config changed
        current_calc_config_hash = self._calc_config_hash(config, is_tomorrow=False)
        calc_config_changed = (
            self._previous_calc_config_hash is not None and
            self._previous_calc_config_hash != current_calc_config_hash
        )

        _LOGGER.debug(f"Price data changed: {price_data_changed}")
        _LOGGER.debug(f"Config changed: {config_changed}")
        _LOGGER.debug(f"Is first load: {is_first_load}")
        _LOGGER.debug(f"Scheduled update: {scheduled_update}")
        _LOGGER.debug(f"Automation enabled: {current_automation_enabled} (was: {self._previous_automation_enabled})")
        _LOGGER.debug(f"Calc config hash: {current_calc_config_hash} (was: {self._previous_calc_config_hash})")
        _LOGGER.debug(f"Calc config changed: {calc_config_changed}")

        # Check if automation_enabled changed - this requires recalculation
        # Only detect change if we have a previous value (not on very first load)
        automation_enabled_changed = (
            self._previous_automation_enabled is not None and
            self._previous_automation_enabled != current_automation_enabled
        )

        # Only skip recalculation for non-calculation config changes
        # Always recalculate for:
        # - First load
        # - Price data changed
        # - Calculation config changed
        # - Scheduled updates (needed for time-based state changes)
        if config_changed and not price_data_changed and not is_first_load and not calc_config_changed and not scheduled_update:
            # Non-calculation config change (notifications, etc.) - maintain current state
            _LOGGER.debug("Non-calculation config change, skipping recalculation to prevent spurious state changes")
            return

        if calc_config_changed:
            _LOGGER.info(f"Calculation config changed, forcing recalculation")

        if scheduled_update:
            _LOGGER.debug("Scheduled update - recalculating for time-based state changes")

        # On first load, we need to calculate to set initial state even though it's a config change
        if is_first_load:
            _LOGGER.debug("First load - calculating initial state")


        # Price data changed OR first run - proceed with recalculation
        raw_today = self.coordinator.data.get("raw_today", [])

        _LOGGER.debug(f"Raw today length: {len(raw_today)}")
        _LOGGER.debug(f"Config keys: {len(list(config.keys()))} items")
        _LOGGER.debug(f"Automation enabled: {config.get('automation_enabled')}")

        # Calculate windows and state
        if raw_today:
            _LOGGER.debug("Calculating windows...")

            result = self._calculation_engine.calculate_windows(
                raw_today, config, is_tomorrow=False
            )

            calculated_state = result.get("state", STATE_OFF)
            _LOGGER.debug(f"Calculated state: {calculated_state}")
            _LOGGER.debug(f"Charge windows: {len(result.get('cheapest_times', []))}")
            _LOGGER.debug(f"Discharge windows: {len(result.get('expensive_times', []))}")

            new_state = calculated_state
            new_attributes = self._build_attributes(result)
        else:
            # No data available
            automation_enabled = config.get("automation_enabled", True)
            state = STATE_OFF if not automation_enabled else STATE_IDLE
            _LOGGER.debug(f"No raw_today data, setting state to: {state}")

            new_state = state
            new_attributes = self._build_attributes({})

        # Only update if state or attributes have changed
        state_changed = new_state != self._previous_state
        attributes_changed = new_attributes != self._previous_attributes

        if state_changed or attributes_changed:
            if state_changed:
                _LOGGER.info(f"State changed: {self._previous_state} → {new_state}")
            else:
                _LOGGER.debug("Attributes changed, updating sensor")

            self._attr_native_value = new_state
            self._attr_extra_state_attributes = new_attributes
            self._previous_state = new_state
            self._previous_attributes = new_attributes.copy() if new_attributes else None
            self._previous_automation_enabled = current_automation_enabled
            self._previous_calc_config_hash = current_calc_config_hash
            self._persistent_sensor_state["previous_automation_enabled"] = current_automation_enabled
            self._persistent_sensor_state["previous_calc_config_hash"] = current_calc_config_hash

            _LOGGER.debug(f"Final state: {self._attr_native_value}")
            _LOGGER.debug("-"*60)
            self.async_write_ha_state()
        else:
            _LOGGER.debug("No changes detected, maintaining current state")
            # Still update tracking even if state didn't change
            self._previous_automation_enabled = current_automation_enabled
            self._previous_calc_config_hash = current_calc_config_hash
            self._persistent_sensor_state["previous_automation_enabled"] = current_automation_enabled
            self._persistent_sensor_state["previous_calc_config_hash"] = current_calc_config_hash

    def _build_attributes(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Build sensor attributes from calculation result."""
        # Get last config update time from coordinator data
        last_config_update = self.coordinator.data.get("last_config_update") if self.coordinator.data else None

        return {
            ATTR_CHEAPEST_TIMES: result.get("cheapest_times", []),
            ATTR_CHEAPEST_PRICES: result.get("cheapest_prices", []),
            ATTR_EXPENSIVE_TIMES: result.get("expensive_times", []),
            ATTR_EXPENSIVE_PRICES: result.get("expensive_prices", []),
            ATTR_EXPENSIVE_TIMES_AGGRESSIVE: result.get("expensive_times_aggressive", []),
            ATTR_EXPENSIVE_PRICES_AGGRESSIVE: result.get("expensive_prices_aggressive", []),
            ATTR_ACTUAL_CHARGE_TIMES: result.get("actual_charge_times", []),
            ATTR_ACTUAL_CHARGE_PRICES: result.get("actual_charge_prices", []),
            ATTR_ACTUAL_DISCHARGE_TIMES: result.get("actual_discharge_times", []),
            ATTR_ACTUAL_DISCHARGE_PRICES: result.get("actual_discharge_prices", []),
            ATTR_COMPLETED_CHARGE_WINDOWS: result.get("completed_charge_windows", 0),
            ATTR_COMPLETED_DISCHARGE_WINDOWS: result.get("completed_discharge_windows", 0),
            ATTR_COMPLETED_CHARGE_COST: result.get("completed_charge_cost", 0.0),
            ATTR_COMPLETED_DISCHARGE_REVENUE: result.get("completed_discharge_revenue", 0.0),
            ATTR_NUM_WINDOWS: result.get("num_windows", 0),
            ATTR_MIN_SPREAD_REQUIRED: result.get("min_spread_required", 0.0),
            ATTR_SPREAD_PERCENTAGE: result.get("spread_percentage", 0.0),
            ATTR_SPREAD_MET: result.get("spread_met", False),
            ATTR_SPREAD_AVG: result.get("spread_avg", 0.0),
            ATTR_ACTUAL_SPREAD_AVG: result.get("actual_spread_avg", 0.0),
            ATTR_DISCHARGE_SPREAD_MET: result.get("discharge_spread_met", False),
            ATTR_AGGRESSIVE_DISCHARGE_SPREAD_MET: result.get("aggressive_discharge_spread_met", False),
            ATTR_AVG_CHEAP_PRICE: result.get("avg_cheap_price", 0.0),
            ATTR_AVG_EXPENSIVE_PRICE: result.get("avg_expensive_price", 0.0),
            ATTR_CURRENT_PRICE: result.get("current_price", 0.0),
            ATTR_PRICE_OVERRIDE_ACTIVE: result.get("price_override_active", False),
            ATTR_TIME_OVERRIDE_ACTIVE: result.get("time_override_active", False),
            "last_config_update": last_config_update.isoformat() if last_config_update else None,
        }


class CEWTomorrowSensor(CEWBaseSensor):
    """Sensor for tomorrow's energy windows."""

    def __init__(self, coordinator: CEWCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize tomorrow sensor."""
        super().__init__(coordinator, config_entry, "tomorrow")
        self._calculation_engine = WindowCalculationEngine()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.data:
            # No coordinator data - maintain previous state if we have one
            if self._previous_state is not None:
                _LOGGER.debug("No coordinator data, maintaining previous tomorrow state")
                return
            else:
                new_state = STATE_OFF
                new_attributes = {}
                self._attr_native_value = new_state
                self._attr_extra_state_attributes = new_attributes
                self._previous_state = new_state
                self._previous_attributes = new_attributes.copy() if new_attributes else None
                self.async_write_ha_state()
                return

        # Layer 3: Check what changed
        price_data_changed = self.coordinator.data.get("price_data_changed", True)
        config_changed = self.coordinator.data.get("config_changed", False)
        is_first_load = self.coordinator.data.get("is_first_load", False)
        scheduled_update = self.coordinator.data.get("scheduled_update", False)

        config = self.coordinator.data.get("config", {})
        current_automation_enabled = config.get("automation_enabled", True)

        # Check if calculation-affecting config changed
        current_calc_config_hash = self._calc_config_hash(config, is_tomorrow=True)
        calc_config_changed = (
            self._previous_calc_config_hash is not None and
            self._previous_calc_config_hash != current_calc_config_hash
        )

        # Only skip recalculation for non-calculation config changes
        # Always recalculate for scheduled updates (needed for time-based state changes)
        if config_changed and not price_data_changed and not is_first_load and not calc_config_changed and not scheduled_update:
            _LOGGER.debug("Tomorrow: Non-calculation config change, skipping recalculation")
            return

        if calc_config_changed:
            _LOGGER.info(f"Tomorrow: Calculation config changed, forcing recalculation")

        if scheduled_update:
            _LOGGER.debug("Tomorrow: Scheduled update - recalculating for time-based state changes")

        # On first load, calculate to set initial state
        if is_first_load:
            _LOGGER.debug("Tomorrow: First load - calculating initial state")

        # Price data changed OR first run - proceed with recalculation
        tomorrow_valid = self.coordinator.data.get("tomorrow_valid", False)
        raw_tomorrow = self.coordinator.data.get("raw_tomorrow", [])

        if tomorrow_valid and raw_tomorrow:
            # Calculate tomorrow's windows
            result = self._calculation_engine.calculate_windows(
                raw_tomorrow, config, is_tomorrow=True
            )

            # Get calculated state from result (like today sensor does)
            new_state = result.get("state", STATE_OFF)
            new_attributes = self._build_attributes(result)
        else:
            # No tomorrow data yet (Nordpool publishes after 13:00 CET)
            new_state = STATE_OFF
            new_attributes = {}

        # Only update if state or attributes have changed
        state_changed = new_state != self._previous_state
        attributes_changed = new_attributes != self._previous_attributes

        if state_changed or attributes_changed:
            if state_changed:
                _LOGGER.info(f"Tomorrow state changed: {self._previous_state} → {new_state}")
            else:
                _LOGGER.debug("Tomorrow attributes changed, updating sensor")

            self._attr_native_value = new_state
            self._attr_extra_state_attributes = new_attributes
            self._previous_state = new_state
            self._previous_attributes = new_attributes.copy() if new_attributes else None
            self._previous_automation_enabled = current_automation_enabled
            self._previous_calc_config_hash = current_calc_config_hash
            self._persistent_sensor_state["previous_automation_enabled"] = current_automation_enabled
            self._persistent_sensor_state["previous_calc_config_hash"] = current_calc_config_hash
            self.async_write_ha_state()
        else:
            _LOGGER.debug("No changes in tomorrow sensor, maintaining current state")
            # Still update tracking even if state didn't change
            self._previous_automation_enabled = current_automation_enabled
            self._previous_calc_config_hash = current_calc_config_hash
            self._persistent_sensor_state["previous_automation_enabled"] = current_automation_enabled
            self._persistent_sensor_state["previous_calc_config_hash"] = current_calc_config_hash

    def _build_attributes(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Build sensor attributes for tomorrow."""
        # Get last config update time from coordinator data
        last_config_update = self.coordinator.data.get("last_config_update") if self.coordinator.data else None

        # Tomorrow sensor has fewer attributes (no completed windows, etc.)
        return {
            ATTR_CHEAPEST_TIMES: result.get("cheapest_times", []),
            ATTR_CHEAPEST_PRICES: result.get("cheapest_prices", []),
            ATTR_EXPENSIVE_TIMES: result.get("expensive_times", []),
            ATTR_EXPENSIVE_PRICES: result.get("expensive_prices", []),
            ATTR_EXPENSIVE_TIMES_AGGRESSIVE: result.get("expensive_times_aggressive", []),
            ATTR_EXPENSIVE_PRICES_AGGRESSIVE: result.get("expensive_prices_aggressive", []),
            ATTR_NUM_WINDOWS: result.get("num_windows", 0),
            ATTR_MIN_SPREAD_REQUIRED: result.get("min_spread_required", 0.0),
            ATTR_SPREAD_PERCENTAGE: result.get("spread_percentage", 0.0),
            ATTR_SPREAD_MET: result.get("spread_met", False),
            ATTR_AVG_CHEAP_PRICE: result.get("avg_cheap_price", 0.0),
            ATTR_AVG_EXPENSIVE_PRICE: result.get("avg_expensive_price", 0.0),
            "last_config_update": last_config_update.isoformat() if last_config_update else None,
        }