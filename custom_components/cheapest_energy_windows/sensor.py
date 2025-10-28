"""Sensor platform for Cheapest Energy Windows."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional
import uuid

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
        CEWPriceSensorProxy(hass, coordinator, config_entry),
        CEWLastCalculationSensor(coordinator, config_entry),
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
            config.get(f"calculation_window_enabled{suffix}", False),
            config.get(f"calculation_window_start{suffix}", "00:00:00"),
            config.get(f"calculation_window_end{suffix}", "23:59:59"),
        ]

        # Add time overrides (these affect current state)
        calc_values.extend([
            config.get(f"time_override_enabled{suffix}", False),
            config.get(f"time_override_start{suffix}", "00:00:00"),
            config.get(f"time_override_end{suffix}", "00:00:00"),
            config.get(f"time_override_mode{suffix}", "charge"),
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
            self._previous_calc_config_hash is None or
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
            self._previous_calc_config_hash is None or
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
            ATTR_ACTUAL_CHARGE_TIMES: result.get("actual_charge_times", []),
            ATTR_ACTUAL_CHARGE_PRICES: result.get("actual_charge_prices", []),
            ATTR_ACTUAL_DISCHARGE_TIMES: result.get("actual_discharge_times", []),
            ATTR_ACTUAL_DISCHARGE_PRICES: result.get("actual_discharge_prices", []),
            ATTR_NUM_WINDOWS: result.get("num_windows", 0),
            ATTR_MIN_SPREAD_REQUIRED: result.get("min_spread_required", 0.0),
            ATTR_SPREAD_PERCENTAGE: result.get("spread_percentage", 0.0),
            ATTR_SPREAD_MET: result.get("spread_met", False),
            ATTR_AVG_CHEAP_PRICE: result.get("avg_cheap_price", 0.0),
            ATTR_AVG_EXPENSIVE_PRICE: result.get("avg_expensive_price", 0.0),
            "last_config_update": last_config_update.isoformat() if last_config_update else None,
        }


class CEWPriceSensorProxy(SensorEntity):
    """Proxy sensor that mirrors the configured price sensor.

    This allows the dashboard to use a consistent sensor entity_id
    regardless of which price sensor the user has configured.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CEWCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the proxy sensor."""
        self.hass = hass
        self.coordinator = coordinator
        self.config_entry = config_entry

        self._attr_unique_id = f"{PREFIX}price_sensor_proxy"
        self._attr_name = "CEW Price Sensor Proxy"
        self._attr_has_entity_name = False
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}

        _LOGGER.debug("Price sensor proxy initialized")

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": "Cheapest Energy Windows",
            "manufacturer": "Community",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }

    @property
    def should_poll(self) -> bool:
        """No polling needed - updates come from coordinator."""
        return False

    def _detect_sensor_format(self, attributes):
        """Detect sensor format type."""
        if "raw_today" in attributes and "raw_tomorrow" in attributes:
            return "nordpool"
        elif "prices_today" in attributes or "prices_tomorrow" in attributes:
            return "entsoe"
        # Future: Add more formats here
        return None

    def _normalize_entsoe_to_nordpool(self, attributes):
        """Convert ENTSO-E format to Nord Pool format."""
        from datetime import timedelta
        normalized = {}

        # Convert prices_today to raw_today
        if "prices_today" in attributes and attributes["prices_today"]:
            raw_today = []
            for item in attributes["prices_today"]:
                time_str = item.get("time", "")
                parsed = dt_util.parse_datetime(time_str)
                if parsed:
                    # Convert UTC to local timezone
                    local_time = dt_util.as_local(parsed)
                    end_time = local_time + timedelta(minutes=15)
                    raw_today.append({
                        "start": local_time.isoformat(),
                        "end": end_time.isoformat(),
                        "value": item.get("price", 0)
                    })
            normalized["raw_today"] = raw_today
        else:
            normalized["raw_today"] = []

        # Convert prices_tomorrow to raw_tomorrow
        if "prices_tomorrow" in attributes and attributes["prices_tomorrow"]:
            raw_tomorrow = []
            for item in attributes["prices_tomorrow"]:
                time_str = item.get("time", "")
                parsed = dt_util.parse_datetime(time_str)
                if parsed:
                    # Convert UTC to local timezone
                    local_time = dt_util.as_local(parsed)
                    end_time = local_time + timedelta(minutes=15)
                    raw_tomorrow.append({
                        "start": local_time.isoformat(),
                        "end": end_time.isoformat(),
                        "value": item.get("price", 0)
                    })
            normalized["raw_tomorrow"] = raw_tomorrow
            normalized["tomorrow_valid"] = True
        else:
            normalized["raw_tomorrow"] = []
            normalized["tomorrow_valid"] = False

        # Pass through other attributes we might need
        for key, value in attributes.items():
            if key not in ["prices_today", "prices_tomorrow", "prices", "raw_prices"]:
                normalized[key] = value

        return normalized

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.data:
            return

        # Get the configured price sensor entity_id
        price_sensor_entity = self.hass.states.get(f"text.{PREFIX}price_sensor_entity")
        if not price_sensor_entity:
            _LOGGER.warning("Price sensor entity text input not found")
            return

        price_sensor_id = price_sensor_entity.state
        if not price_sensor_id or price_sensor_id == "":
            _LOGGER.warning("Price sensor entity not configured")
            return

        # Get the actual price sensor state
        price_sensor = self.hass.states.get(price_sensor_id)
        if not price_sensor:
            _LOGGER.warning(f"Configured price sensor {price_sensor_id} not found")
            self._attr_native_value = STATE_UNAVAILABLE
            self.async_write_ha_state()
            return

        # Mirror the state
        self._attr_native_value = price_sensor.state

        # Detect format and normalize if needed
        sensor_format = self._detect_sensor_format(price_sensor.attributes)

        if sensor_format == "entsoe":
            _LOGGER.debug(f"Detected ENTSO-E format from {price_sensor_id}, normalizing to Nord Pool format")
            self._attr_extra_state_attributes = self._normalize_entsoe_to_nordpool(price_sensor.attributes)
        elif sensor_format == "nordpool":
            _LOGGER.debug(f"Detected Nord Pool format from {price_sensor_id}, passing through")
            self._attr_extra_state_attributes = dict(price_sensor.attributes)
        else:
            _LOGGER.warning(f"Unknown price sensor format from {price_sensor_id}, passing through as-is")
            self._attr_extra_state_attributes = dict(price_sensor.attributes)

        _LOGGER.debug(f"Proxy sensor updated from {price_sensor_id}, state: {self._attr_native_value}")
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        # Subscribe to coordinator updates
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

        # Do initial update
        self._handle_coordinator_update()


class CEWLastCalculationSensor(CoordinatorEntity, SensorEntity):
    """Sensor that tracks calculation updates with unique state values.

    This sensor generates a unique random value on every coordinator update
    to trigger chart refreshes via a hidden series in the dashboard.
    Using random values ensures state changes are always detected,
    even with rapid consecutive updates.
    """

    def __init__(
        self,
        coordinator: CEWCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self._attr_unique_id = f"{PREFIX}last_calculation"
        self._attr_name = "CEW Last Calculation"
        self._attr_has_entity_name = False
        self._attr_icon = "mdi:refresh"

        # Initialize with random value
        self._attr_native_value = str(uuid.uuid4())[:8]

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": "Cheapest Energy Windows",
            "manufacturer": "Community",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.data:
            return

        # Only update when calculations actually change
        # Coordinator polls every 10s for state transitions, but this sensor
        # only updates when price data changes or config changes to avoid
        # unnecessary chart refreshes
        price_data_changed = self.coordinator.data.get("price_data_changed", False)
        config_changed = self.coordinator.data.get("config_changed", False)

        if price_data_changed or config_changed:
            # Actual calculation occurred - generate new unique value
            self._attr_native_value = str(uuid.uuid4())[:8]
            self.async_write_ha_state()
            _LOGGER.debug(f"Last calculation updated: {self._attr_native_value} (price_changed={price_data_changed}, config_changed={config_changed})")

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        # Subscribe to coordinator updates
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

        # Do initial update
        self._handle_coordinator_update()