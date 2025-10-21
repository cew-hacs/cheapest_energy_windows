"""Automation handler for Cheapest Energy Windows."""
from __future__ import annotations

from datetime import datetime, time
import logging
from typing import Optional

from homeassistant.const import (
    SERVICE_TURN_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)

from .const import (
    DOMAIN,
    LOGGER_NAME,
    PREFIX,
    STATE_IDLE,
    STATE_OFF,
    EVENT_SETTINGS_ROTATED,
)

_LOGGER = logging.getLogger(LOGGER_NAME)


class AutomationHandler:
    """Handles automations for Cheapest Energy Windows."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the automation handler."""
        self.hass = hass
        self._midnight_listener = None
        self._state_listener = None
        self._last_state = None
        self._last_meaningful_state = None  # Track last non-unavailable state

    async def async_setup(self) -> None:
        """Set up automation handlers."""
        # Set up midnight rotation
        await self._setup_midnight_rotation()

        # Set up state change listener (for logging and filtering only)
        await self._setup_state_listener()

        _LOGGER.info("Automation handlers set up successfully")

    async def async_shutdown(self) -> None:
        """Shut down automation handlers."""
        if self._midnight_listener:
            self._midnight_listener()
            self._midnight_listener = None

        if self._state_listener:
            self._state_listener()
            self._state_listener = None

        _LOGGER.info("Automation handlers shut down")

    async def _setup_midnight_rotation(self) -> None:
        """Set up midnight settings rotation."""
        @callback
        async def midnight_rotation(now: datetime) -> None:
            """Rotate tomorrow's settings to today at midnight."""
            # Check if tomorrow settings are enabled
            tomorrow_enabled = self.hass.states.get(f"switch.{PREFIX}tomorrow_settings_enabled")
            if not tomorrow_enabled or tomorrow_enabled.state != STATE_ON:
                _LOGGER.debug("Tomorrow settings not enabled, skipping rotation")
                return

            _LOGGER.info("Starting midnight settings rotation")

            # Rotate settings
            await self._rotate_settings()

            # Disable tomorrow settings
            await self.hass.services.async_call(
                "switch",
                SERVICE_TURN_OFF,
                {
                    "entity_id": f"switch.{PREFIX}tomorrow_settings_enabled",
                },
            )

            # Fire event for any listeners
            self.hass.bus.async_fire(EVENT_SETTINGS_ROTATED)

            _LOGGER.info("Midnight settings rotation complete")

        # Schedule rotation at midnight
        self._midnight_listener = async_track_time_change(
            self.hass,
            midnight_rotation,
            hour=0,
            minute=0,
            second=0,
        )

        _LOGGER.debug("Midnight rotation scheduled")

    async def _rotate_settings(self) -> None:
        """Rotate tomorrow's settings to today."""
        # List of settings to rotate
        settings_map = {
            "charging_windows": "charging_windows_tomorrow",
            "expensive_windows": "expensive_windows_tomorrow",
            "cheap_percentile": "cheap_percentile_tomorrow",
            "expensive_percentile": "expensive_percentile_tomorrow",
            "min_spread": "min_spread_tomorrow",
            "min_spread_discharge": "min_spread_discharge_tomorrow",
            "aggressive_discharge_spread": "aggressive_discharge_spread_tomorrow",
            "min_price_difference": "min_price_difference_tomorrow",
            "price_override_threshold": "price_override_threshold_tomorrow",
            "price_override_enabled": "price_override_enabled_tomorrow",
            "time_override_enabled": "time_override_enabled_tomorrow",
            "time_override_start": "time_override_start_tomorrow",
            "time_override_end": "time_override_end_tomorrow",
            "time_override_mode": "time_override_mode_tomorrow",
        }

        # Get config entry
        entry = None
        if DOMAIN in self.hass.data:
            for entry_id in self.hass.data[DOMAIN]:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry:
                    break

        if not entry:
            _LOGGER.error("Could not find config entry for settings rotation")
            return

        # Get current options
        new_options = dict(entry.options)

        # Copy tomorrow's values to today
        for today_key, tomorrow_key in settings_map.items():
            if tomorrow_key in new_options:
                new_options[today_key] = new_options[tomorrow_key]
                _LOGGER.debug(f"Rotated {tomorrow_key} → {today_key}")

        # Update the config entry
        self.hass.config_entries.async_update_entry(entry, options=new_options)

        _LOGGER.info(f"Rotated {len(settings_map)} settings from tomorrow to today")

    async def _setup_state_listener(self) -> None:
        """Set up state change listener for the cew_today sensor."""
        @callback
        async def state_changed(event):
            """Handle state change events."""
            new_state = event.data.get("new_state")
            if not new_state:
                return

            state = new_state.state
            _LOGGER.debug(f"CEW state changed from {self._last_state} to {state}")

            previous_state = self._last_state

            # Track state changes but handle unavailable specially
            self._last_state = state

            # Ignore unavailable/unknown states completely
            if state in ["unavailable", "unknown", None, ""]:
                _LOGGER.debug(f"Ignoring '{state}' state")
                return

            # Filter out transitions from unavailable/unknown to idle
            # These happen during dashboard interactions and aren't meaningful
            if state == STATE_IDLE and previous_state in ["unavailable", "unknown", None, ""]:
                _LOGGER.debug(f"Ignoring transition from '{previous_state}' to idle (not meaningful)")
                # Update meaningful state but don't process further
                self._last_meaningful_state = state
                return

            # Filter out spurious unavailable transitions during first load
            if state == "unavailable":
                coordinator_data = None
                if DOMAIN in self.hass.data:
                    for entry_id, entry_data in self.hass.data[DOMAIN].items():
                        if "coordinator" in entry_data:
                            coordinator = entry_data["coordinator"]
                            if coordinator.data:
                                coordinator_data = coordinator.data
                                break

                if coordinator_data:
                    is_first_load = coordinator_data.get("is_first_load", False)
                    if is_first_load:
                        _LOGGER.debug(f"Ignoring spurious transition to 'unavailable' during initialization")
                        return

            # Only log if state actually changed from the last meaningful state
            if state == self._last_meaningful_state:
                _LOGGER.debug(f"State unchanged from last meaningful: {state}")
                return

            _LOGGER.info(f"State changed: {self._last_meaningful_state} → {state}")
            self._last_meaningful_state = state

            # Note: All notification/automation logic has been removed.
            # State change notifications and battery control actions are now
            # handled by the HA automation (automations.yaml).

        # Subscribe to state changes
        self._state_listener = async_track_state_change_event(
            self.hass,
            [f"sensor.{PREFIX}today"],
            state_changed,
        )

        _LOGGER.debug("State change listener set up")


async def async_setup_automation(hass: HomeAssistant) -> AutomationHandler:
    """Set up automation handler."""
    handler = AutomationHandler(hass)
    await handler.async_setup()
    return handler
