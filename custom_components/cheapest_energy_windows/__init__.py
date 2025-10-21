"""The Cheapest Energy Windows integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    PLATFORMS,
    PREFIX,
    LOGGER_NAME,
    EVENT_SETTINGS_ROTATED,
)
from .coordinator import CEWCoordinator
from .services import async_setup_services
from .automation_handler import async_setup_automation

_LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Cheapest Energy Windows component."""
    # This is called when the component is set up through configuration.yaml
    # We only support config_flow, so we just return True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cheapest Energy Windows from a config entry."""
    _LOGGER.info("="*60)
    _LOGGER.info("INTEGRATION SETUP START")
    _LOGGER.info("="*60)

    # Store domain data
    hass.data.setdefault(DOMAIN, {})

    # Create device registry entry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="Community",
        model="Energy Optimizer",
        name="Cheapest Energy Windows",
        sw_version="1.0.0",
    )

    # No entity creation needed - platforms will create their own entities
    _LOGGER.info("Setting up Cheapest Energy Windows integration")

    # Set up the coordinator for data fetching
    coordinator = CEWCoordinator(hass, entry)

    # Store coordinator BEFORE platforms so they can access it
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Set up platforms FIRST so entities exist
    _LOGGER.info(f"Setting up platforms: {PLATFORMS}")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("All platforms set up successfully")

    # NOW do the first coordinator refresh after entities exist
    _LOGGER.info("Triggering first coordinator refresh")
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("First coordinator refresh complete")

    # Set up services
    await async_setup_services(hass)

    # Set up automation handler
    automation_handler = await async_setup_automation(hass)

    # Store automation handler for cleanup
    hass.data[DOMAIN][entry.entry_id]["automation_handler"] = automation_handler

    # Register update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("="*60)
    _LOGGER.info("INTEGRATION SETUP COMPLETE")
    _LOGGER.info("="*60)

    # Migration from YAML no longer needed - entities are created automatically

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Cheapest Energy Windows integration")

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Shut down automation handler
        automation_handler = hass.data[DOMAIN][entry.entry_id].get("automation_handler")
        if automation_handler:
            await automation_handler.async_shutdown()

        # Clean up domain data
        hass.data[DOMAIN].pop(entry.entry_id)

        # Clean up services if this was the last instance
        if not hass.data[DOMAIN]:
            # TODO: Unregister services
            pass

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    _LOGGER.debug("Options updated, checking if reload needed")

    # Only reload if critical settings changed that require entity recreation
    # Most config changes are handled by coordinator refresh without reload
    # This prevents entity destruction/recreation on every config change

    # Currently, we don't reload automatically - entities handle their own updates
    # Future: Add logic here to reload ONLY if price_sensor_entity changed
    pass


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.info(f"Migrating configuration from version {config_entry.version}")

    # No migrations needed yet for version 1
    if config_entry.version == 1:
        return True

    _LOGGER.error(f"Unknown config version {config_entry.version}")
    return False


