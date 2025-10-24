"""Config flow for Cheapest Energy Windows integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_PRICE_SENSOR,
    CONF_VAT_RATE,
    CONF_TAX,
    CONF_ADDITIONAL_COST,
    CONF_BATTERY_SYSTEM_NAME,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_ENERGY_SENSOR,
    CONF_BATTERY_CHARGE_SENSOR,
    CONF_BATTERY_DISCHARGE_SENSOR,
    CONF_BATTERY_POWER_SENSOR,
    DEFAULT_PRICE_SENSOR,
    DEFAULT_VAT_RATE,
    DEFAULT_TAX,
    DEFAULT_ADDITIONAL_COST,
    DEFAULT_CHARGE_POWER,
    DEFAULT_DISCHARGE_POWER,
    DEFAULT_BATTERY_RTE,
    DEFAULT_CHARGING_WINDOWS,
    DEFAULT_EXPENSIVE_WINDOWS,
    DEFAULT_CHEAP_PERCENTILE,
    DEFAULT_EXPENSIVE_PERCENTILE,
    DEFAULT_MIN_SPREAD,
    DEFAULT_MIN_SPREAD_DISCHARGE,
    DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD,
    DEFAULT_MIN_PRICE_DIFFERENCE,
    DEFAULT_PRICE_OVERRIDE_THRESHOLD,
    PRICING_15_MINUTES,
    PRICING_1_HOUR,
    LOGGER_NAME,
    PREFIX,
)

_LOGGER = logging.getLogger(LOGGER_NAME)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    # Check if price sensor exists
    price_sensor = data.get(CONF_PRICE_SENSOR)
    if price_sensor:
        sensor_state = hass.states.get(price_sensor)
        if not sensor_state:
            raise ValueError(f"Price sensor {price_sensor} not found")

        # Check if it has the required attributes
        if not hasattr(sensor_state, 'attributes'):
            raise ValueError(f"Price sensor {price_sensor} has no attributes")

        attrs = sensor_state.attributes
        if 'raw_today' not in attrs:
            raise ValueError(f"Price sensor {price_sensor} missing 'raw_today' attribute")

        # Check if sensor uses cents instead of EUR/kWh
        if attrs.get('price_in_cents') is True:
            raise ValueError(f"Price sensor {price_sensor} uses cents/kWh. Only EUR/kWh sensors are supported.")

    return {"title": "Cheapest Energy Windows"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cheapest Energy Windows."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self.data = {}
        self.options = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Directly start guided setup
        return await self.async_step_dependencies()

    async def async_step_dependencies(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Check for required dependencies and auto-continue."""
        # Auto-continue to price sensor (dependencies info shown in price sensor step)
        return await self.async_step_price_sensor()

    async def async_step_price_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the price sensor."""
        errors = {}

        if user_input is not None:
            # Validate the price sensor
            try:
                await validate_input(self.hass, user_input)
                self.data.update(user_input)
                return await self.async_step_costs()
            except ValueError as e:
                errors["base"] = "invalid_price_sensor"
                _LOGGER.error(f"Price sensor validation failed: {e}")

        # Try to auto-detect price sensors
        price_sensors = []
        for state in self.hass.states.async_all("sensor"):
            if state.attributes.get("raw_today") is not None:
                # Exclude sensors with price_in_cents enabled
                if state.attributes.get("price_in_cents") is True:
                    continue
                price_sensors.append(state.entity_id)

        # Show error if no sensors found
        if not price_sensors:
            return self.async_show_form(
                step_id="price_sensor",
                data_schema=vol.Schema({}),
                errors={"base": "no_price_sensors"},
                description_placeholders={
                    "info": "⚠️ No compatible price sensors found!\n\nPlease install the Nordpool integration from HACS first:\n1. Go to HACS → Integrations\n2. Search for 'Nordpool'\n3. Install and configure it\n4. Return here to continue setup\n\nThe sensor must have a 'raw_today' attribute with hourly or 15-minute price data."
                },
            )

        # Show available sensors for selection (no default)
        return self.async_show_form(
            step_id="price_sensor",
            data_schema=vol.Schema({
                vol.Required(CONF_PRICE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
            }),
            errors=errors,
            description_placeholders={
                "info": f"✅ Detected {len(price_sensors)} compatible price sensor(s)\n\n⚠️ **IMPORTANT - Price Unit Requirement:**\nYour price sensor MUST use EUR/kWh (e.g., 0.25), NOT cents (e.g., 25).\nSensors configured for cents/kWh are currently not supported and will cause incorrect calculations.\n\nPlease select your price sensor:\n{chr(10).join('- ' + s for s in price_sensors[:5])}\n\nThe sensor must have 'raw_today' attribute with hourly or 15-minute price data."
            },
        )

    async def async_step_costs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure cost parameters."""
        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_power()

        return self.async_show_form(
            step_id="costs",
            data_schema=vol.Schema({
                vol.Required(CONF_VAT_RATE, default=DEFAULT_VAT_RATE): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
                vol.Required(CONF_TAX, default=DEFAULT_TAX): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
                vol.Required(CONF_ADDITIONAL_COST, default=DEFAULT_ADDITIONAL_COST): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=1)
                ),
            }),
            description_placeholders={
                "vat_help": "VAT rate as decimal (e.g., 0.21 for 21%)",
                "tax_help": "Tax per kWh in EUR",
                "cost_help": "Additional costs per kWh in EUR",
            },
        )

    async def async_step_power(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure battery power parameters."""
        if user_input is not None:
            # Store power values in options
            self.options["charge_power"] = user_input.get("charge_power", DEFAULT_CHARGE_POWER)
            self.options["discharge_power"] = user_input.get("discharge_power", DEFAULT_DISCHARGE_POWER)
            self.options["battery_rte"] = user_input.get("battery_rte", DEFAULT_BATTERY_RTE)
            return await self.async_step_pricing_windows()

        return self.async_show_form(
            step_id="power",
            data_schema=vol.Schema({
                vol.Required("charge_power", default=DEFAULT_CHARGE_POWER): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=10000)
                ),
                vol.Required("discharge_power", default=DEFAULT_DISCHARGE_POWER): vol.All(
                    vol.Coerce(int), vol.Range(min=100, max=10000)
                ),
                vol.Required("battery_rte", default=DEFAULT_BATTERY_RTE): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=100)
                ),
            }),
            description_placeholders={
                "charge_help": "Battery charging power in Watts (800W is typical for single battery)",
                "discharge_help": "Battery discharging power in Watts",
                "rte_help": "Round-trip efficiency 50-100% (85% typical, accounts for conversion losses)",
                "note": "These values are used to calculate energy capacity (kWh) for charging/discharging windows",
            },
        )

    async def async_step_pricing_windows(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure pricing window duration and spread settings."""
        if user_input is not None:
            # Store all pricing window settings in options
            self.options.update(user_input)
            return await self.async_step_battery()

        return self.async_show_form(
            step_id="pricing_windows",
            data_schema=vol.Schema({
                vol.Required("pricing_window_duration", default=PRICING_1_HOUR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"label": "15 Minutes (96 windows per day)", "value": PRICING_15_MINUTES},
                            {"label": "1 Hour (24 windows per day)", "value": PRICING_1_HOUR},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("charging_windows", default=DEFAULT_CHARGING_WINDOWS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=96,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("expensive_windows", default=DEFAULT_EXPENSIVE_WINDOWS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=96,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("cheap_percentile", default=DEFAULT_CHEAP_PERCENTILE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=50,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("expensive_percentile", default=DEFAULT_EXPENSIVE_PERCENTILE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=50,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("min_spread", default=DEFAULT_MIN_SPREAD): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("min_spread_discharge", default=DEFAULT_MIN_SPREAD_DISCHARGE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=200,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("aggressive_discharge_spread", default=DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=300,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional("min_price_difference", default=DEFAULT_MIN_PRICE_DIFFERENCE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=0.5,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required("price_override_enabled", default=False): selector.BooleanSelector(),
                vol.Optional("price_override_threshold", default=DEFAULT_PRICE_OVERRIDE_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=0.5,
                        step=0.01,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }),
            description_placeholders={
                "info": f"Configure pricing window duration and optimization settings.\n\n15 Minutes: More granular optimization (use if your contract has 15-minute pricing)\n1 Hour: Standard hourly optimization (use if your contract has hourly pricing)\n\nSpread settings control when to charge/discharge based on price differences.\n\nPrice Override: Always charge when price is below threshold, regardless of spread/windows.\n\nDefaults:\n- Charging Windows: {DEFAULT_CHARGING_WINDOWS}\n- Discharge Windows: {DEFAULT_EXPENSIVE_WINDOWS}\n- Percentiles: {DEFAULT_CHEAP_PERCENTILE}% cheap, {DEFAULT_EXPENSIVE_PERCENTILE}% expensive\n- Min Spreads: {DEFAULT_MIN_SPREAD}% charge, {DEFAULT_MIN_SPREAD_DISCHARGE}% discharge, {DEFAULT_AGGRESSIVE_DISCHARGE_SPREAD}% aggressive\n- Price Override: Disabled, €{DEFAULT_PRICE_OVERRIDE_THRESHOLD}/kWh"
            },
        )

    async def async_step_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure battery system (optional)."""
        if user_input is not None:
            # Check if user actually entered any battery data
            battery_data = {
                k: v for k, v in user_input.items()
                if v is not None and v != "" and v != "not_configured"
            }

            # Save to both data and options so entities can access it
            if battery_data:
                self.data.update(battery_data)
                self.options.update(battery_data)

            return await self.async_step_battery_operations()

        return self.async_show_form(
            step_id="battery",
            data_schema=vol.Schema({
                vol.Optional(CONF_BATTERY_SYSTEM_NAME): cv.string,
                vol.Optional(CONF_BATTERY_SOC_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(CONF_BATTERY_ENERGY_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(CONF_BATTERY_CHARGE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(CONF_BATTERY_DISCHARGE_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(CONF_BATTERY_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
            }),
            description_placeholders={
                "info": "Optional: Configure battery system sensors for monitoring and automation.\n\nLeave fields empty to skip battery configuration.\n\nYou can configure these later through the integration settings."
            },
        )

    async def async_step_battery_operations(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure battery operation automations."""
        if user_input is not None:
            # Set default "not_configured" for any empty/missing fields
            battery_ops = {
                "battery_idle_action": user_input.get("battery_idle_action", "not_configured"),
                "battery_charge_action": user_input.get("battery_charge_action", "not_configured"),
                "battery_discharge_action": user_input.get("battery_discharge_action", "not_configured"),
                "battery_aggressive_discharge_action": user_input.get("battery_aggressive_discharge_action", "not_configured"),
                "battery_off_action": user_input.get("battery_off_action", "not_configured"),
            }
            self.data.update(battery_ops)
            return await self.async_step_automation()

        return self.async_show_form(
            step_id="battery_operations",
            data_schema=vol.Schema({
                vol.Optional("battery_idle_action"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["automation", "script", "scene"],
                        multiple=False,
                    )
                ),
                vol.Optional("battery_charge_action"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["automation", "script", "scene"],
                        multiple=False,
                    )
                ),
                vol.Optional("battery_discharge_action"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["automation", "script", "scene"],
                        multiple=False,
                    )
                ),
                vol.Optional("battery_aggressive_discharge_action"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["automation", "script", "scene"],
                        multiple=False,
                    )
                ),
                vol.Optional("battery_off_action"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["automation", "script", "scene"],
                        multiple=False,
                    )
                ),
            }),
            description_placeholders={
                "info": "⚙️ **Battery Operations (Optional)**\n\nLink existing automations, scripts, or scenes to battery modes. They'll be triggered automatically when modes change.\n\n**How it works:**\n- Create your battery control automations/scripts first\n- Select them from the dropdowns below\n- CEW will automatically trigger them when entering each mode\n\nLeave blank to configure later in Settings → Battery Operations."
            },
        )

    async def async_step_automation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create notification automation."""
        errors = {}

        if user_input is not None:
            # Import the function here to avoid circular imports
            from .services import async_create_notification_automation

            # Create the automation
            success, message = await async_create_notification_automation(self.hass)

            if success:
                _LOGGER.info(f"Automation creation: {message}")
                # Store success message to show in confirmation step
                self.options["_automation_created"] = True
                self.options["_automation_message"] = message
                return await self.async_step_dashboard()
            else:
                _LOGGER.error(f"Automation creation failed: {message}")
                errors["base"] = "automation_creation_failed"
                # Store error message for display
                self.options["_automation_error"] = message

        return self.async_show_form(
            step_id="automation",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "info": "🤖 **Create Battery Control Automation**\n\n"
                       "A battery control automation will be created automatically for you.\n\n"
                       "**What it provides:**\n"
                       "- Triggers on CEW state changes (charge, discharge, idle, off)\n"
                       "- Placeholders for YOUR battery control actions\n"
                       "- Template you customize for your specific battery system\n\n"
                       "**What it does NOT provide:**\n"
                       "- ❌ Notifications (handled by built-in AutomationHandler)\n"
                       "- ❌ Automatic battery control (you add those actions)\n\n"
                       "**After setup:**\n"
                       "1. Go to **Settings** → **Automations & Scenes**\n"
                       "2. Find **CEW - Battery Control Automation**\n"
                       "3. Edit it and add your battery device actions to each trigger\n"
                       "4. Each trigger has a persistent notification placeholder showing what action to add\n\n"
                       "**Important switches to enable for notifications:**\n"
                       "- switch.cew_automation_enabled (master switch - MUST be ON)\n"
                       "- switch.cew_notifications_enabled (enables notifications)\n"
                       "- Individual notification toggles (notify_charging, notify_discharge, etc.)\n\n"
                       "Click **Submit** to create the automation."
            },
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm configuration and complete setup."""
        if user_input is not None:
            # Complete setup
            return self.async_create_entry(
                title="Cheapest Energy Windows",
                data=self.data,
                options=self.options,
            )

        # Show summary of what will be created
        charge_power = self.options.get("charge_power", DEFAULT_CHARGE_POWER)
        discharge_power = self.options.get("discharge_power", DEFAULT_DISCHARGE_POWER)
        pricing_duration = self.options.get("pricing_window_duration", PRICING_15_MINUTES)
        charging_windows = self.options.get("charging_windows", DEFAULT_CHARGING_WINDOWS)
        expensive_windows = self.options.get("expensive_windows", DEFAULT_EXPENSIVE_WINDOWS)

        battery_configured = self.data.get(CONF_BATTERY_SYSTEM_NAME) is not None
        automation_created = self.options.get("_automation_created", False)
        automation_message = self.options.get("_automation_message", "")

        summary = f"""
Configuration Summary:
- Price Sensor: {self.data.get(CONF_PRICE_SENSOR, DEFAULT_PRICE_SENSOR)}
- VAT Rate: {self.data.get(CONF_VAT_RATE, DEFAULT_VAT_RATE) * 100:.0f}%
- Tax: €{self.data.get(CONF_TAX, DEFAULT_TAX):.5f}/kWh
- Additional Cost: €{self.data.get(CONF_ADDITIONAL_COST, DEFAULT_ADDITIONAL_COST):.5f}/kWh
- Charge Power: {charge_power}W
- Discharge Power: {discharge_power}W
- Pricing Duration: {pricing_duration.replace('_', ' ').title()}
- Charging Windows: {charging_windows}
- Discharge Windows: {expensive_windows}
- Battery Configured: {'Yes' if battery_configured else 'No'}

This will create:
- 2 sensors (CEW Today, CEW Tomorrow)
- 27 number entities (pricing, power, battery config)
- 26 switch entities (automation toggles, battery display)
- 7 select entities (modes, duration)
- 6 time entities (schedules, overrides)
- 6 text entities (sensor entity IDs, battery config)

Total: 71 entities
"""

        if automation_created:
            summary += f"\n✅ Automation Status: {automation_message}\n"
            summary += "Find it in Settings → Automations & Scenes\n"

        summary += "\nClick Submit to complete setup!"

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "summary": summary,
            },
        )

    async def async_step_dashboard(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show dashboard installation instructions."""
        if user_input is not None:
            # Move to confirmation step
            return await self.async_step_confirm()

        return self.async_show_form(
            step_id="dashboard",
            data_schema=vol.Schema({}),
            description_placeholders={
                "info": "📊 **Dashboard Available via HACS**\n\n"
                       "A beautiful, pre-configured dashboard is available as a separate HACS plugin.\n\n"
                       "**Why install from HACS?**\n"
                       "✅ Automatic updates when improvements are released\n"
                       "✅ One-click installation\n"
                       "✅ Always stays in sync with integration features\n\n"
                       "**To install the dashboard:**\n\n"
                       "1. Go to **HACS** → **Frontend**\n"
                       "2. Click **Explore & Download Repositories**\n"
                       "3. Search for **\"Cheapest Energy Windows Dashboard\"**\n"
                       "4. Click **Download**\n"
                       "5. Follow the HACS installation instructions\n"
                       "6. The dashboard will appear in your sidebar automatically\n\n"
                       "**Dashboard Features:**\n"
                       "- Real-time energy price monitoring with ApexCharts visualizations\n"
                       "- Visual charge/discharge windows display\n"
                       "- Battery system status and metrics\n"
                       "- Quick access to all settings in collapsible sections\n"
                       "- Responsive mobile-friendly design\n\n"
                       "Click **Submit** to complete the setup."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return CEWOptionsFlow(config_entry)


class CEWOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Cheapest Energy Windows."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_PRICE_SENSOR,
                    default=options.get(
                        CONF_PRICE_SENSOR,
                        self.config_entry.data.get(CONF_PRICE_SENSOR, DEFAULT_PRICE_SENSOR)
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        multiple=False,
                    )
                ),
                vol.Optional(
                    CONF_VAT_RATE,
                    default=options.get(
                        CONF_VAT_RATE,
                        self.config_entry.data.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
                vol.Optional(
                    CONF_TAX,
                    default=options.get(
                        CONF_TAX,
                        self.config_entry.data.get(CONF_TAX, DEFAULT_TAX)
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
                vol.Optional(
                    CONF_ADDITIONAL_COST,
                    default=options.get(
                        CONF_ADDITIONAL_COST,
                        self.config_entry.data.get(CONF_ADDITIONAL_COST, DEFAULT_ADDITIONAL_COST)
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            }),
        )