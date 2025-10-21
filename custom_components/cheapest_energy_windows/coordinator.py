"""Data coordinator for Cheapest Energy Windows."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER_NAME,
    UPDATE_INTERVAL,
    CONF_PRICE_SENSOR,
    DEFAULT_PRICE_SENSOR,
    PREFIX,
)

_LOGGER = logging.getLogger(LOGGER_NAME)


class CEWCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Cheapest Energy Windows data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )

        self.config_entry = config_entry
        self.price_sensor = config_entry.data.get(CONF_PRICE_SENSOR, DEFAULT_PRICE_SENSOR)

        # Cache for price sensor entity ID (from input_text)
        self._price_sensor_entity: Optional[str] = None
        self._last_price_sensor_check: Optional[datetime] = None

        # Debouncing for rapid refreshes
        self._debounce_timer = None
        self._debounce_delay = 3.0  # 3 second debounce (Layer 4: increased from 1s)

        # Track previous price data to detect changes (Layer 2)
        # Store in hass.data to persist across integration reloads
        persistent_key = f"{DOMAIN}_{config_entry.entry_id}_price_state"
        if persistent_key not in hass.data:
            hass.data[persistent_key] = {
                "previous_raw_today": None,
                "previous_raw_tomorrow": None,
                "last_price_update": None,
                "last_config_update": None,
                "previous_config_hash": None,
            }
        self._persistent_state = hass.data[persistent_key]

        # Instance variables (for convenience, but backed by persistent storage)
        self._previous_raw_today: Optional[list] = self._persistent_state["previous_raw_today"]
        self._previous_raw_tomorrow: Optional[list] = self._persistent_state["previous_raw_tomorrow"]
        self._last_price_update: Optional[datetime] = self._persistent_state["last_price_update"]
        self._last_config_update: Optional[datetime] = self._persistent_state["last_config_update"]
        self._previous_config_hash: Optional[str] = self._persistent_state["previous_config_hash"]

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from price sensor."""
        _LOGGER.info("="*60)
        _LOGGER.info("COORDINATOR UPDATE START")
        _LOGGER.info("="*60)

        try:
            # Get the price sensor entity ID from input_text (user configurable)
            price_sensor = await self._get_price_sensor_entity()
            _LOGGER.info(f"Price sensor entity ID: {price_sensor}")

            if not price_sensor:
                _LOGGER.warning("No price sensor configured, returning empty data")
                return await self._empty_data("No price sensor configured")

            # Get the price sensor state
            price_state = self.hass.states.get(price_sensor)
            _LOGGER.info(f"Price sensor state exists: {price_state is not None}")

            if not price_state:
                _LOGGER.warning(f"Price sensor {price_sensor} not found, returning empty data")
                _LOGGER.info(f"Available sensors: {[e for e in self.hass.states.async_entity_ids() if 'nordpool' in e or 'price' in e]}")
                return await self._empty_data(f"Price sensor {price_sensor} not found")

            _LOGGER.info(f"Price sensor state: {price_state.state}")
            _LOGGER.info(f"Price sensor attributes keys: {list(price_state.attributes.keys())}")

            # Extract price data
            raw_today = price_state.attributes.get("raw_today", [])
            raw_tomorrow = price_state.attributes.get("raw_tomorrow", [])
            tomorrow_valid = price_state.attributes.get("tomorrow_valid", False)

            _LOGGER.info(f"Raw today count: {len(raw_today)}")
            _LOGGER.info(f"Raw tomorrow count: {len(raw_tomorrow)}")
            _LOGGER.info(f"Tomorrow valid: {tomorrow_valid}")

            if not raw_today:
                _LOGGER.warning("No price data available for today")
                _LOGGER.info(f"raw_today value: {raw_today}")
                return await self._empty_data("No price data available")

            # Get configuration from config entry options (Layer 1: no race conditions)
            config = await self._get_configuration()
            _LOGGER.debug(f"Config keys loaded: {list(config.keys())}")
            _LOGGER.debug(f"Automation enabled: {config.get('automation_enabled', 'NOT SET')}")
            _LOGGER.debug(f"Charging windows: {config.get('charging_windows', 'NOT SET')}")

            # Layer 2: Detect what changed
            now = dt_util.now()
            price_data_changed = False
            config_changed = False
            is_first_load = False
            scheduled_update = False  # New: track scheduled updates where nothing changed

            # Check if price data changed
            # Compare lengths and a hash of the data for more reliable comparison
            def _price_data_hash(data):
                """Create a simple hash of price data for comparison."""
                if not data:
                    return ""
                # Create hash from length and first/last items
                try:
                    return f"{len(data)}_{data[0].get('value', 0)}_{data[-1].get('value', 0)}"
                except (IndexError, AttributeError, TypeError):
                    return str(len(data))

            def _config_hash(cfg):
                """Create a simple hash of config for comparison."""
                # Convert config dict to a sorted tuple of items for consistent hashing
                try:
                    return str(hash(tuple(sorted((k, str(v)) for k, v in cfg.items()))))
                except (TypeError, AttributeError):
                    return str(cfg)

            current_today_hash = _price_data_hash(raw_today)
            current_tomorrow_hash = _price_data_hash(raw_tomorrow)
            previous_today_hash = _price_data_hash(self._previous_raw_today)
            previous_tomorrow_hash = _price_data_hash(self._previous_raw_tomorrow)

            current_config_hash = _config_hash(config)
            previous_config_hash = self._previous_config_hash

            _LOGGER.debug(f"Today hash: {current_today_hash} vs {previous_today_hash}")
            _LOGGER.debug(f"Tomorrow hash: {current_tomorrow_hash} vs {previous_tomorrow_hash}")
            _LOGGER.debug(f"Config hash: {current_config_hash} vs {previous_config_hash}")

            # Check if this is the first load (no previous data)
            if not previous_today_hash and not previous_tomorrow_hash:
                # First load after restart/reload - treat as initialization, not a real update
                is_first_load = True
                config_changed = True  # Treat as config change to avoid state transitions
                self._last_config_update = now
                self._persistent_state["last_config_update"] = now
                _LOGGER.info("FIRST LOAD - Initializing without triggering state changes")
            elif current_today_hash != previous_today_hash or current_tomorrow_hash != previous_tomorrow_hash:
                price_data_changed = True
                self._last_price_update = now
                self._persistent_state["last_price_update"] = now
                _LOGGER.info("PRICE DATA CHANGED - This is a real update")
            elif previous_config_hash and current_config_hash != previous_config_hash:
                config_changed = True
                self._last_config_update = now
                self._persistent_state["last_config_update"] = now
                _LOGGER.info("CONFIG CHANGED - User updated settings")
            else:
                # Nothing changed - this is a scheduled update for time-based state changes
                scheduled_update = True
                _LOGGER.info("SCHEDULED UPDATE - No price or config changes")

            # Store current price data and config hash for next comparison
            self._previous_raw_today = raw_today.copy() if raw_today else []
            self._previous_raw_tomorrow = raw_tomorrow.copy() if raw_tomorrow else []
            self._previous_config_hash = current_config_hash
            self._persistent_state["previous_raw_today"] = self._previous_raw_today
            self._persistent_state["previous_raw_tomorrow"] = self._previous_raw_tomorrow
            self._persistent_state["previous_config_hash"] = current_config_hash

            # Process the data with metadata
            data = {
                "price_sensor": price_sensor,
                "raw_today": raw_today,
                "raw_tomorrow": raw_tomorrow,
                "tomorrow_valid": tomorrow_valid,
                "config": config,
                "last_update": now,
                # Layer 2: Change tracking metadata
                "price_data_changed": price_data_changed,
                "config_changed": config_changed,
                "is_first_load": is_first_load,
                "scheduled_update": scheduled_update,
                "last_price_update": self._last_price_update,
                "last_config_update": self._last_config_update,
            }

            _LOGGER.info(f"Data structure keys: {list(data.keys())}")
            _LOGGER.info(f"Price data changed: {price_data_changed}")
            _LOGGER.info(f"Config changed: {config_changed}")
            _LOGGER.info("COORDINATOR UPDATE SUCCESS")
            _LOGGER.info("="*60)
            return data

        except Exception as e:
            _LOGGER.error(f"COORDINATOR UPDATE FAILED: {e}", exc_info=True)
            _LOGGER.info("="*60)
            raise UpdateFailed(f"Error fetching data: {e}") from e

    async def _get_price_sensor_entity(self) -> Optional[str]:
        """Get the configured price sensor entity ID."""
        # Check cache (refresh every 5 minutes)
        now = datetime.now()
        if self._price_sensor_entity and self._last_price_sensor_check:
            if now - self._last_price_sensor_check < timedelta(minutes=5):
                return self._price_sensor_entity

        # Get from text entity
        text_entity = f"text.{PREFIX}price_sensor_entity"
        state = self.hass.states.get(text_entity)

        if state and state.state and state.state not in ["", "unknown", "unavailable", "none"]:
            self._price_sensor_entity = state.state
        else:
            # Fall back to config entry
            self._price_sensor_entity = self.price_sensor

        self._last_price_sensor_check = now
        return self._price_sensor_entity

    async def _get_configuration(self) -> Dict[str, Any]:
        """Get current configuration from config entry options.

        Reading from config_entry.options instead of entity states eliminates
        race conditions where entity states might be temporarily unavailable
        during updates.
        """
        from .const import (
            DEFAULT_CHARGING_WINDOWS,
            DEFAULT_EXPENSIVE_WINDOWS,
            DEFAULT_CHEAP_PERCENTILE,
            DEFAULT_EXPENSIVE_PERCENTILE,
            DEFAULT_MIN_SPREAD,
            DEFAULT_MIN_SPREAD_DISCHARGE,
            DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD,
            DEFAULT_MIN_PRICE_DIFFERENCE,
            DEFAULT_ADDITIONAL_COST,
            DEFAULT_TAX,
            DEFAULT_VAT_RATE,
            DEFAULT_BATTERY_RTE,
            DEFAULT_CHARGE_POWER,
            DEFAULT_DISCHARGE_POWER,
            DEFAULT_PRICE_OVERRIDE_THRESHOLD,
            DEFAULT_QUIET_START,
            DEFAULT_QUIET_END,
            DEFAULT_TIME_OVERRIDE_START,
            DEFAULT_TIME_OVERRIDE_END,
            DEFAULT_CALCULATION_WINDOW_START,
            DEFAULT_CALCULATION_WINDOW_END,
            DEFAULT_BATTERY_MIN_SOC_DISCHARGE,
            DEFAULT_BATTERY_MIN_SOC_AGGRESSIVE_DISCHARGE,
        )

        options = self.config_entry.options

        _LOGGER.debug(f"Building config from options. calculation_window_enabled raw value: {options.get('calculation_window_enabled', 'NOT SET')}")

        # Number values with defaults
        config = {
            # Today's configuration
            "charging_windows": float(options.get("charging_windows", DEFAULT_CHARGING_WINDOWS)),
            "expensive_windows": float(options.get("expensive_windows", DEFAULT_EXPENSIVE_WINDOWS)),
            "cheap_percentile": float(options.get("cheap_percentile", DEFAULT_CHEAP_PERCENTILE)),
            "expensive_percentile": float(options.get("expensive_percentile", DEFAULT_EXPENSIVE_PERCENTILE)),
            "min_spread": float(options.get("min_spread", DEFAULT_MIN_SPREAD)),
            "min_spread_discharge": float(options.get("min_spread_discharge", DEFAULT_MIN_SPREAD_DISCHARGE)),
            "aggressive_discharge_spread": float(options.get("aggressive_discharge_spread", DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD)),
            "min_price_difference": float(options.get("min_price_difference", DEFAULT_MIN_PRICE_DIFFERENCE)),
            "additional_cost": float(options.get("additional_cost", DEFAULT_ADDITIONAL_COST)),
            "tax": float(options.get("tax", DEFAULT_TAX)),
            "vat": float(options.get("vat", DEFAULT_VAT_RATE)),
            "battery_rte": float(options.get("battery_rte", DEFAULT_BATTERY_RTE)),
            "charge_power": float(options.get("charge_power", DEFAULT_CHARGE_POWER)),
            "discharge_power": float(options.get("discharge_power", DEFAULT_DISCHARGE_POWER)),
            "price_override_threshold": float(options.get("price_override_threshold", DEFAULT_PRICE_OVERRIDE_THRESHOLD)),
            "battery_min_soc_discharge": float(options.get("battery_min_soc_discharge", DEFAULT_BATTERY_MIN_SOC_DISCHARGE)),
            "battery_min_soc_aggressive_discharge": float(options.get("battery_min_soc_aggressive_discharge", DEFAULT_BATTERY_MIN_SOC_AGGRESSIVE_DISCHARGE)),

            # Tomorrow's configuration
            "charging_windows_tomorrow": float(options.get("charging_windows_tomorrow", DEFAULT_CHARGING_WINDOWS)),
            "expensive_windows_tomorrow": float(options.get("expensive_windows_tomorrow", DEFAULT_EXPENSIVE_WINDOWS)),
            "cheap_percentile_tomorrow": float(options.get("cheap_percentile_tomorrow", DEFAULT_CHEAP_PERCENTILE)),
            "expensive_percentile_tomorrow": float(options.get("expensive_percentile_tomorrow", DEFAULT_EXPENSIVE_PERCENTILE)),
            "min_spread_tomorrow": float(options.get("min_spread_tomorrow", DEFAULT_MIN_SPREAD)),
            "min_spread_discharge_tomorrow": float(options.get("min_spread_discharge_tomorrow", DEFAULT_MIN_SPREAD_DISCHARGE)),
            "aggressive_discharge_spread_tomorrow": float(options.get("aggressive_discharge_spread_tomorrow", DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD)),
            "min_price_difference_tomorrow": float(options.get("min_price_difference_tomorrow", DEFAULT_MIN_PRICE_DIFFERENCE)),
            "price_override_threshold_tomorrow": float(options.get("price_override_threshold_tomorrow", DEFAULT_PRICE_OVERRIDE_THRESHOLD)),

            # Boolean values (switches)
            "automation_enabled": bool(options.get("automation_enabled", True)),
            "tomorrow_settings_enabled": bool(options.get("tomorrow_settings_enabled", False)),
            "midnight_rotation_notifications": bool(options.get("midnight_rotation_notifications", False)),
            "notifications_enabled": bool(options.get("notifications_enabled", True)),
            "quiet_hours_enabled": bool(options.get("quiet_hours_enabled", False)),
            "price_override_enabled": bool(options.get("price_override_enabled", False)),
            "price_override_enabled_tomorrow": bool(options.get("price_override_enabled_tomorrow", False)),
            "time_override_1_enabled": bool(options.get("time_override_1_enabled", False)),
            "time_override_1_enabled_tomorrow": bool(options.get("time_override_1_enabled_tomorrow", False)),
            "calculation_window_enabled": bool(options.get("calculation_window_enabled", False)),
            "notify_automation_disabled": bool(options.get("notify_automation_disabled", False)),
            "notify_charging": bool(options.get("notify_charging", True)),
            "notify_discharge": bool(options.get("notify_discharge", True)),
            "notify_discharge_aggressive": bool(options.get("notify_discharge_aggressive", True)),
            "notify_idle": bool(options.get("notify_idle", False)),

            # String values (selects)
            "pricing_window_duration": options.get("pricing_window_duration", "15_minutes"),
            "time_override_1_mode": options.get("time_override_1_mode", "charge"),
            "time_override_1_mode_tomorrow": options.get("time_override_1_mode_tomorrow", "charge"),

            # Time values
            "time_override_1_start": options.get("time_override_1_start", DEFAULT_TIME_OVERRIDE_START),
            "time_override_1_end": options.get("time_override_1_end", DEFAULT_TIME_OVERRIDE_END),
            "time_override_1_start_tomorrow": options.get("time_override_1_start_tomorrow", DEFAULT_TIME_OVERRIDE_START),
            "time_override_1_end_tomorrow": options.get("time_override_1_end_tomorrow", DEFAULT_TIME_OVERRIDE_END),
            "calculation_window_start": options.get("calculation_window_start", DEFAULT_CALCULATION_WINDOW_START),
            "calculation_window_end": options.get("calculation_window_end", DEFAULT_CALCULATION_WINDOW_END),
            "quiet_hours_start": options.get("quiet_hours_start", DEFAULT_QUIET_START),
            "quiet_hours_end": options.get("quiet_hours_end", DEFAULT_QUIET_END),
        }

        return config

    async def async_request_refresh(self) -> None:
        """Request a refresh with debouncing."""
        # Cancel any pending refresh
        if self._debounce_timer:
            self._debounce_timer.cancel()

        # Schedule new refresh after debounce delay
        async def _do_refresh():
            """Perform the actual refresh."""
            _LOGGER.debug("Executing debounced refresh")
            # Call the parent's async_refresh() to actually fetch new data
            await super(CEWCoordinator, self).async_refresh()

        self._debounce_timer = self.hass.loop.call_later(
            self._debounce_delay,
            lambda: asyncio.create_task(_do_refresh())
        )
        _LOGGER.debug(f"Refresh requested, debouncing for {self._debounce_delay}s")

    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Get a configuration value from the coordinator data."""
        if self.data and "config" in self.data:
            return self.data["config"].get(key, default)
        return default

    async def _empty_data(self, reason: str) -> Dict[str, Any]:
        """Return empty data structure when price sensor is not available."""
        # Still get config so settings are available
        config = await self._get_configuration()

        return {
            "price_sensor": None,
            "raw_today": [],
            "raw_tomorrow": [],
            "tomorrow_valid": False,
            "config": config,
            "last_update": dt_util.now(),
            "error": reason,
        }