"""Services for Cheapest Energy Windows."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import yaml

from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import (
    DOMAIN,
    LOGGER_NAME,
    PREFIX,
    SERVICE_ROTATE_SETTINGS,
    EVENT_SETTINGS_ROTATED,
)

_LOGGER = logging.getLogger(LOGGER_NAME)

# Service schemas
SERVICE_ROTATE_SCHEMA = vol.Schema({})


async def async_create_notification_automation(hass: HomeAssistant) -> tuple[bool, str]:
    """Create the notification automation in automations.yaml.

    Returns:
        tuple[bool, str]: (Success status, Message)
    """
    try:
        automation_id = f"{DOMAIN}_notifications"

        # Get the path to automations.yaml
        automations_path = hass.config.path("automations.yaml")
        _LOGGER.info(f"Automations file path: {automations_path}")

        # Read existing automations (non-blocking)
        existing_automations = []
        if Path(automations_path).exists():
            try:
                def read_automations_file():
                    with open(automations_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        if content.strip():
                            return yaml.safe_load(content) or []
                    return []

                existing_automations = await hass.async_add_executor_job(read_automations_file)

                if not isinstance(existing_automations, list):
                    existing_automations = [existing_automations]

                # Remove existing automation if present (to update with latest template)
                existing_automations = [
                    auto for auto in existing_automations
                    if not (isinstance(auto, dict) and auto.get("id") == automation_id)
                ]
                _LOGGER.info(f"Updating automation {automation_id} with latest template")

            except yaml.YAMLError as e:
                _LOGGER.error(f"Error parsing existing automations.yaml: {e}")
                return False, f"Failed to parse existing automations: {e}"

        # Load automation template from automation_template.yaml
        # This is the single source of truth for the automation structure
        template_path = Path(__file__).parent / "automation_template.yaml"
        _LOGGER.info(f"Loading automation template from: {template_path}")

        try:
            def read_template_file():
                with open(template_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    return yaml.safe_load(content)

            template_automation = await hass.async_add_executor_job(read_template_file)

            # The template is already in the correct format, just need to add the ID
            if not isinstance(template_automation, dict):
                raise ValueError("automation_template.yaml must contain a single automation dictionary")

            # Set the automation ID (template might have a different one)
            template_automation["id"] = automation_id

            new_automation = template_automation
            _LOGGER.info(f"Successfully loaded automation template (using notify.notify notifications)")

        except Exception as e:
            _LOGGER.error(f"Error loading automation_template.yaml: {e}")
            _LOGGER.warning("Falling back to basic automation structure")

            # Fallback to minimal automation if template can't be loaded
            new_automation = {
            "id": automation_id,
            "alias": "CEW - Battery Control Automation",
            "description": "Battery control automation for Cheapest Energy Windows (add your battery actions to each trigger)",
            "mode": "queued",
            "max": 10,
            "trigger": [
                {
                    "platform": "state",
                    "entity_id": f"sensor.{PREFIX}today",
                    "to": "charge",
                    "from": ["discharge", "discharge_aggressive", "idle", "off"],
                    "id": "charge_start"
                },
                {
                    "platform": "state",
                    "entity_id": f"sensor.{PREFIX}today",
                    "to": "discharge",
                    "from": ["charge", "discharge_aggressive", "idle", "off"],
                    "id": "discharge_start"
                },
                {
                    "platform": "state",
                    "entity_id": f"sensor.{PREFIX}today",
                    "to": "discharge_aggressive",
                    "from": ["charge", "discharge", "idle", "off"],
                    "id": "discharge_aggressive_start"
                },
                {
                    "platform": "state",
                    "entity_id": f"sensor.{PREFIX}today",
                    "to": "idle",
                    "from": ["charge", "discharge", "discharge_aggressive", "off"],
                    "id": "idle_start"
                },
                {
                    "platform": "state",
                    "entity_id": f"sensor.{PREFIX}today",
                    "to": "off",
                    "from": ["charge", "discharge", "discharge_aggressive", "idle"],
                    "id": "automation_disabled"
                }
            ],
            "condition": [],
            "action": [
                {
                    "choose": [
                        {
                            "conditions": [
                                {"condition": "trigger", "id": "charge_start"}
                            ],
                            "sequence": [
                                {
                                    "service": "persistent_notification.create",
                                    "data": {
                                        "title": "CEW Battery Action Needed",
                                        "message": (
                                            "⚠️ CHARGE trigger fired but no battery action configured.\n\n"
                                            "Edit this automation and add your battery CHARGE action here.\n"
                                            "Example: Turn on battery charge mode, set charge power, etc."
                                        ),
                                        "notification_id": "cew_charge_action_needed"
                                    }
                                }
                            ]
                        },
                        {
                            "conditions": [
                                {"condition": "trigger", "id": "discharge_start"}
                            ],
                            "sequence": [
                                {
                                    "service": "persistent_notification.create",
                                    "data": {
                                        "title": "CEW Battery Action Needed",
                                        "message": (
                                            "⚠️ DISCHARGE trigger fired but no battery action configured.\n\n"
                                            "Edit this automation and add your battery DISCHARGE action here.\n"
                                            "Example: Turn on battery discharge mode, set discharge power, etc."
                                        ),
                                        "notification_id": "cew_discharge_action_needed"
                                    }
                                }
                            ]
                        },
                        {
                            "conditions": [
                                {"condition": "trigger", "id": "discharge_aggressive_start"}
                            ],
                            "sequence": [
                                {
                                    "service": "persistent_notification.create",
                                    "data": {
                                        "title": "CEW Battery Action Needed",
                                        "message": (
                                            "⚠️ AGGRESSIVE DISCHARGE trigger fired but no battery action configured.\n\n"
                                            "Edit this automation and add your battery AGGRESSIVE DISCHARGE action here.\n"
                                            "Example: Set maximum discharge power for peak price periods."
                                        ),
                                        "notification_id": "cew_discharge_aggressive_action_needed"
                                    }
                                }
                            ]
                        },
                        {
                            "conditions": [
                                {"condition": "trigger", "id": "idle_start"}
                            ],
                            "sequence": [
                                {
                                    "service": "persistent_notification.create",
                                    "data": {
                                        "title": "CEW Battery Action Needed",
                                        "message": (
                                            "⚠️ IDLE trigger fired but no battery action configured.\n\n"
                                            "Edit this automation and add your battery IDLE action here.\n"
                                            "Example: Set battery to standby mode, 0W charge/discharge, etc."
                                        ),
                                        "notification_id": "cew_idle_action_needed"
                                    }
                                }
                            ]
                        },
                        {
                            "conditions": [
                                {"condition": "trigger", "id": "automation_disabled"}
                            ],
                            "sequence": [
                                {
                                    "service": "persistent_notification.create",
                                    "data": {
                                        "title": "CEW Automation Disabled",
                                        "message": (
                                            "CEW automation has been disabled.\n\n"
                                            "You can add a battery STOP/MANUAL mode action here if needed."
                                        ),
                                        "notification_id": "cew_automation_disabled"
                                    }
                                }
                            ]
                        }
                    ],
                    "default": []
                }
            ]
        }

        # Add to existing automations
        existing_automations.append(new_automation)

        # Write to file (non-blocking)
        def write_automations_file():
            with open(automations_path, "w", encoding="utf-8") as f:
                yaml.dump(existing_automations, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        await hass.async_add_executor_job(write_automations_file)

        _LOGGER.info(f"Successfully wrote automation to {automations_path}")

        # Reload automations
        try:
            await hass.services.async_call(
                "automation",
                "reload",
                {},
                blocking=True
            )
            _LOGGER.info("Automations reloaded successfully")
            return True, "Automation created successfully!"
        except Exception as e:
            _LOGGER.warning(f"Failed to reload automations: {e}. Automation will load on next restart.")
            return True, "Automation created! Please restart Home Assistant to activate it."

    except Exception as e:
        _LOGGER.error(f"Error creating automation: {e}", exc_info=True)
        return False, f"Failed to create automation: {str(e)}"


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Cheapest Energy Windows."""

    async def handle_rotate_settings(call: ServiceCall) -> None:
        """Handle the rotate_settings service call."""
        _LOGGER.info("Rotating tomorrow settings to today")

        # List of settings to rotate
        settings_to_rotate = [
            # Window counts
            ("charging_windows_tomorrow", "charging_windows"),
            ("expensive_windows_tomorrow", "expensive_windows"),
            # Percentiles
            ("cheap_percentile_tomorrow", "cheap_percentile"),
            ("expensive_percentile_tomorrow", "expensive_percentile"),
            # Spreads
            ("min_spread_tomorrow", "min_spread"),
            ("min_spread_discharge_tomorrow", "min_spread_discharge"),
            ("aggressive_discharge_spread_tomorrow", "aggressive_discharge_spread"),
            ("min_price_difference_tomorrow", "min_price_difference"),
            # Price override
            ("price_override_threshold_tomorrow", "price_override_threshold"),
        ]

        # Rotate number settings
        for tomorrow_key, today_key in settings_to_rotate:
            tomorrow_entity = f"number.{PREFIX}{tomorrow_key}"
            today_entity = f"number.{PREFIX}{today_key}"

            tomorrow_state = hass.states.get(tomorrow_entity)
            if tomorrow_state:
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": today_entity, "value": float(tomorrow_state.state)},
                    blocking=True,
                )
                _LOGGER.debug(f"Rotated {tomorrow_key} -> {today_key}: {tomorrow_state.state}")

        # Rotate boolean settings
        boolean_settings = [
            ("price_override_enabled_tomorrow", "price_override_enabled"),
            ("time_override_enabled_tomorrow", "time_override_enabled"),
        ]

        for tomorrow_key, today_key in boolean_settings:
            tomorrow_entity = f"switch.{PREFIX}{tomorrow_key}"
            today_entity = f"switch.{PREFIX}{today_key}"

            tomorrow_state = hass.states.get(tomorrow_entity)
            if tomorrow_state:
                service = "turn_on" if tomorrow_state.state == "on" else "turn_off"
                await hass.services.async_call(
                    "switch",
                    service,
                    {"entity_id": today_entity},
                    blocking=True,
                )
                _LOGGER.debug(f"Rotated {tomorrow_key} -> {today_key}: {tomorrow_state.state}")

        # Rotate select settings
        select_settings = [
            ("time_override_mode_tomorrow", "time_override_mode"),
        ]

        for tomorrow_key, today_key in select_settings:
            tomorrow_entity = f"select.{PREFIX}{tomorrow_key}"
            today_entity = f"select.{PREFIX}{today_key}"

            tomorrow_state = hass.states.get(tomorrow_entity)
            if tomorrow_state:
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": today_entity, "option": tomorrow_state.state},
                    blocking=True,
                )
                _LOGGER.debug(f"Rotated {tomorrow_key} -> {today_key}: {tomorrow_state.state}")

        # Rotate datetime settings
        datetime_settings = [
            ("time_override_start_tomorrow", "time_override_start"),
            ("time_override_end_tomorrow", "time_override_end"),
        ]

        for tomorrow_key, today_key in datetime_settings:
            tomorrow_entity = f"time.{PREFIX}{tomorrow_key}"
            today_entity = f"time.{PREFIX}{today_key}"

            tomorrow_state = hass.states.get(tomorrow_entity)
            if tomorrow_state:
                await hass.services.async_call(
                    "time",
                    "set_value",
                    {"entity_id": today_entity, "time": tomorrow_state.state},
                    blocking=True,
                )
                _LOGGER.debug(f"Rotated {tomorrow_key} -> {today_key}: {tomorrow_state.state}")

        # Disable tomorrow settings
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": f"switch.{PREFIX}tomorrow_settings_enabled"},
            blocking=True,
        )

        # Fire event
        hass.bus.async_fire(EVENT_SETTINGS_ROTATED, {})

        # Send notification if enabled
        if hass.states.is_state(f"switch.{PREFIX}midnight_rotation_notifications", "on"):
            await hass.services.async_call(
                "notify",
                "notify",
                {
                    "title": "CEW Settings Rotated",
                    "message": "Tomorrow's settings have been applied to today",
                },
            )

        _LOGGER.info("Settings rotation complete")

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_ROTATE_SETTINGS,
        handle_rotate_settings,
        schema=SERVICE_ROTATE_SCHEMA,
    )

    _LOGGER.info("Services registered successfully")