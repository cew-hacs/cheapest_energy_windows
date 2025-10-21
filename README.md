# Cheapest Energy Windows for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/cew-hacs/cheapest_energy_windows.svg)](https://github.com/cew-hacs/cheapest_energy_windows/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Optimize your energy consumption and battery storage by automatically identifying the cheapest charging windows and most expensive discharging periods based on dynamic electricity prices from Nord Pool.

## Table of Contents

- [Dashboard Preview](#dashboard-preview)
- [Supported Price Sensors](#supported-price-sensors)
- [Features](#features)
- [Installation](#installation)
  - [HACS Installation](#hacs-installation-recommended)
  - [Manual Installation](#manual-installation)
- [Configuration](#configuration)
  - [Initial Setup](#initial-setup)
- [Dashboard Installation](#dashboard-installation)
  - [Getting the Dashboard File](#getting-the-dashboard-file)
  - [Installation Steps](#installation-steps)
  - [Required Frontend Components](#required-frontend-components)
- [How It Works](#how-it-works)
  - [Window Selection Algorithm](#window-selection-algorithm)
  - [Entities Created](#entities-created)
- [Services](#services)
- [Automation System](#automation-system)
  - [How Automations Work](#how-automations-work)
  - [Initial Setup: Notification-Only Mode](#initial-setup-notification-only-mode)
  - [Adding Battery Control Actions](#adding-battery-control-actions)
- [Sensor Attributes](#sensor-attributes)
- [Dashboard Features](#dashboard-features)
- [Troubleshooting](#troubleshooting)
- [Performance](#performance)
- [Contributing](#contributing)
- [License](#license)
- [Support](#support)

## Dashboard Preview

![Cheapest Energy Windows Dashboard](CEW-Dashboard.jpg?v=2)

## Supported Price Sensors

This integration is designed to work with **Nord Pool** dynamic electricity pricing. It requires a Nord Pool price sensor integration such as:
- [Nordpool](https://github.com/custom-components/nordpool) - Provides hourly electricity prices for Nordic and Baltic countries

The integration supports **flexible time granularity**:
- **15-minute windows** (96 windows per day) - Uses quarter-hourly pricing data from Nord Pool for precise optimization
- **1-hour windows** (24 windows per day) - Aggregates to hourly averages for simpler management

Choose the window duration that matches your energy contract and trading resolution. Many modern dynamic pricing contracts support 15-minute settlements, allowing for more granular optimization opportunities.

While primarily designed for Nord Pool data structure, it may work with other dynamic pricing sensors that provide hourly price data in a similar format (ENTSO-E, Tibber with modifications).

## Features

- **Flexible Window Duration**: Choose between 15-minute (96 windows/day) or 1-hour (24 windows/day) intervals to match your energy contract
- **Smart Window Detection**: Automatically identifies optimal charge/discharge windows based on electricity prices
- **Percentile-Based Selection**: Uses statistical analysis to find truly cheap and expensive periods
- **Progressive Window Selection**: Ensures spread requirements are met for profitability
- **Battery Management**: Control battery charging and discharging based on price optimization
- **Dual-Day Management**: Configure different settings for today and tomorrow
- **Time Overrides**: Set specific time periods to force charging or discharging
- **Comprehensive Dashboard**: Full control interface with real-time status and analytics
- **Automation Support**: Built-in automation for midnight settings rotation and state-based control

## Installation

### HACS Installation (Recommended)

1. Open HACS in your Home Assistant instance
2. Click on "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add this repository URL and select "Integration" as the category
5. Click "Add"
6. Search for "Cheapest Energy Windows"
7. Click "Download"
8. Restart Home Assistant
9. Go to Settings > Devices & Services
10. Click "Add Integration"
11. Search for "Cheapest Energy Windows"
12. Follow the configuration wizard

### Manual Installation

1. Copy the `custom_components/cheapest_energy_windows` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Settings > Devices & Services
4. Click "Add Integration"
5. Search for "Cheapest Energy Windows"
6. Follow the configuration wizard

## Configuration

### Initial Setup

During the configuration flow, you'll be asked to:

1. **Choose setup mode**:
   - Guided Setup (recommended for new users)
   - Quick Setup (for advanced users)

2. **Select your Nord Pool price sensor**: The integration will auto-discover Nord Pool price sensors in your Home Assistant instance

3. **Choose window duration**:
   - **15 minutes** (96 windows per day) - Recommended if your energy contract supports quarter-hourly trading/settlement
   - **1 hour** (24 windows per day) - Simpler management, suitable for hourly contracts

   > **Tip**: Most Nord Pool data includes 15-minute granularity. Choose 15-minute windows for maximum optimization flexibility, or 1-hour windows for simpler scheduling.

4. **Configure pricing parameters**:
   - VAT percentage
   - Additional tax (€/kWh)
   - Fixed additional costs (€/kWh)

5. **Battery settings** (optional):
   - Charge power (Watts)
   - Discharge power (Watts)
   - Round-trip efficiency (%)

You can change the window duration anytime after setup using the `Pricing Window Duration` selector in the dashboard or entity settings.

## Dashboard Installation

The integration includes a comprehensive pre-built dashboard for monitoring and controlling all features. You need to manually install this dashboard using the YAML configuration file.

### Getting the Dashboard File

**Option 1: From your local installation**
- Path: `/config/custom_components/cheapest_energy_windows/main_dashboard.yaml`

**Option 2: Download directly**
- Direct link: [main_dashboard.yaml](https://github.com/cew-hacs/cheapest_energy_windows/blob/main/custom_components/cheapest_energy_windows/main_dashboard.yaml)

### Installation Steps

1. **Create a new dashboard**:
   - Go to **Settings > Dashboards**
   - Click **+ Add Dashboard** (bottom right)
   - Choose **New dashboard from scratch**
   - Give it a name (e.g., "Energy Windows" or "CEW Control")
   - Click **Create**

2. **Add the YAML configuration**:
   - Click the **⋮** menu (three dots) on your new dashboard
   - Select **Edit Dashboard**
   - Click **⋮** menu again and select **Raw configuration editor**
   - Copy the entire contents of `main_dashboard.yaml`
   - Paste it into the editor (replacing any existing content)
   - Click **Save**

3. **Refresh your browser** to ensure all template changes are loaded

### Required Frontend Components

The dashboard requires the following custom cards to be installed via HACS:

1. **[Mushroom Cards](https://github.com/piitaya/lovelace-mushroom)** - Modern card designs
2. **[fold-entity-row](https://github.com/thomasloven/lovelace-fold-entity-row)** - Collapsible entity rows
3. **[ApexCharts Card](https://github.com/RomRider/apexcharts-card)** - Advanced chart rendering

To install these:
- Go to **HACS > Frontend**
- Search for each card name
- Click **Download** and restart Home Assistant

## How It Works

### Window Selection Algorithm

The algorithm operates on either **15-minute or 1-hour intervals** depending on your configuration:

1. **Data Processing**:
   - **15-minute mode**: Uses Nord Pool's quarter-hourly data directly (96 data points per day)
   - **1-hour mode**: Aggregates four 15-minute periods into hourly averages (24 data points per day)

2. **Percentile Filtering**:
   - Identifies the cheapest X% of windows for charging
   - Identifies the most expensive Y% of windows for discharging

3. **Progressive Selection**:
   - Starts with most extreme prices
   - Adds windows while maintaining minimum spread requirements
   - Ensures profitability considering round-trip efficiency

4. **Spread Calculation**:
   ```
   Spread = ((expensive_price - cheap_price) / cheap_price) * 100
   ```

5. **State Determination**:
   - **Charge**: Current window is in cheap windows and spread requirement met
   - **Discharge**: Current window is in expensive windows and spread requirement met
   - **Discharge Aggressive**: Current window meets aggressive discharge spread
   - **Idle**: No conditions met
   - **Off**: Automation disabled

### Entities Created

The integration creates 64 configuration entities:

#### Sensors
- `sensor.cew_today`: Current state and window information for today
- `sensor.cew_tomorrow`: Window information for tomorrow (when available)

#### Input Numbers (24)
- Window counts (charging, expensive)
- Percentiles (cheap, expensive)
- Spreads (minimum, discharge, aggressive)
- Costs (VAT, tax, additional)
- Battery parameters (power, efficiency)
- Price overrides

#### Input Booleans (18)
- Automation enable/disable
- Notification settings
- Time override enables
- Tomorrow settings

#### Input Selects (7)
- Window duration mode
- Time override modes

#### Input DateTimes (14)
- Time override periods
- Quiet hours

#### Input Text (1)
- Price sensor entity ID

## Services

### cheapest_energy_windows.rotate_settings
Apply tomorrow's settings to today. Automatically triggered at midnight when enabled.

This service can be manually called if you want to:
- Force an immediate settings rotation
- Test the settings rotation functionality
- Reset today's settings to match tomorrow's configuration

## Automation System

### How Automations Work

The integration automatically creates **state-based automations** for you during setup. These automations monitor the `sensor.cew_today` state and trigger actions when the state changes between:

- **charge** - Battery should charge during cheap energy windows
- **discharge** - Battery should discharge during expensive energy windows
- **discharge_aggressive** - Battery should discharge aggressively during peak prices
- **idle** - Battery should remain idle (no action)
- **off** - Automation is disabled

### Initial Setup: Notification-Only Mode

**By default**, the integration sets up **notification automations** that alert you when states change. This is a safe starting point that lets you:

✓ Understand how the system works
✓ Verify the window selections are correct
✓ See state changes in real-time
✗ Does NOT control your battery automatically

### Adding Battery Control Actions

To automate your battery, you need to **customize the automations** with your specific battery control actions:

#### Step 1: Find Your Battery Control Entities

First, identify the entities that control your battery:
- Battery charge switch/number (e.g., `switch.battery_charge`, `number.battery_charge_power`)
- Battery discharge switch/number (e.g., `switch.battery_discharge`, `number.battery_discharge_power`)
- Battery mode select (e.g., `select.battery_mode`)

#### Step 2: Edit the Automations

1. Go to **Settings > Automations & Scenes**
2. Find the automations created by CEW (look for "CEW" or "Cheapest Energy Windows" prefix)
3. Click on each automation to edit it
4. Add your battery control actions to the corresponding states

#### Step 3: Automation Examples

**Example 1: Simple Switch Control**

```yaml
automation:
  - alias: "CEW Battery Charge"
    description: "Start battery charging during cheap energy windows"
    trigger:
      - platform: state
        entity_id: sensor.cew_today
        to: 'charge'
    action:
      # Your battery charge action here
      - service: switch.turn_on
        target:
          entity_id: switch.battery_charge
      # Optional: Set charge power
      - service: number.set_value
        target:
          entity_id: number.battery_charge_power
        data:
          value: 2400  # Watts
      # Optional: Send notification
      - service: notify.mobile_app
        data:
          title: "Battery Charging"
          message: "Starting charge at €{{ state_attr('sensor.cew_today', 'avg_cheap_price') }}/kWh"

  - alias: "CEW Battery Discharge"
    description: "Start battery discharging during expensive energy windows"
    trigger:
      - platform: state
        entity_id: sensor.cew_today
        to: 'discharge'
    action:
      # Your battery discharge action here
      - service: switch.turn_on
        target:
          entity_id: switch.battery_discharge
      # Optional: Set discharge power
      - service: number.set_value
        target:
          entity_id: number.battery_discharge_power
        data:
          value: 2400  # Watts

  - alias: "CEW Battery Idle"
    description: "Stop battery activity during idle periods"
    trigger:
      - platform: state
        entity_id: sensor.cew_today
        to: 'idle'
    action:
      # Stop all battery activity
      - service: switch.turn_off
        target:
          entity_id:
            - switch.battery_charge
            - switch.battery_discharge
```

**Example 2: Mode-Based Control (Huawei, SolarEdge, etc.)**

```yaml
automation:
  - alias: "CEW Battery Mode Control"
    description: "Control battery mode based on CEW state"
    trigger:
      - platform: state
        entity_id: sensor.cew_today
    action:
      - choose:
          # Charge mode
          - conditions:
              - condition: state
                entity_id: sensor.cew_today
                state: 'charge'
            sequence:
              - service: select.select_option
                target:
                  entity_id: select.battery_working_mode
                data:
                  option: "Time of Use"
              - service: number.set_value
                target:
                  entity_id: number.battery_charge_power
                data:
                  value: 2400

          # Discharge mode
          - conditions:
              - condition: state
                entity_id: sensor.cew_today
                state: 'discharge'
            sequence:
              - service: select.select_option
                target:
                  entity_id: select.battery_working_mode
                data:
                  option: "Maximise Self Consumption"

          # Idle mode
          - conditions:
              - condition: state
                entity_id: sensor.cew_today
                state: 'idle'
            sequence:
              - service: select.select_option
                target:
                  entity_id: select.battery_working_mode
                data:
                  option: "Fully Fed To Grid"
```

**Example 3: Advanced - Using Time Overrides**

```yaml
automation:
  - alias: "CEW Force Charge Override"
    description: "Force charging during override period"
    trigger:
      - platform: state
        entity_id: input_boolean.cew_time_override_charge_enabled
        to: 'on'
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.battery_charge
      - service: notify.mobile_app
        data:
          title: "Battery Override Active"
          message: "Forcing charge until {{ states('input_datetime.cew_time_override_charge_end') }}"
```

### Using Window Attributes in Automations

You can access detailed window information in your automations:

```yaml
automation:
  - alias: "Morning Energy Report"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: notify.mobile_app
        data:
          title: "Today's Energy Windows"
          message: >
            Charging at: {{ state_attr('sensor.cew_today', 'cheapest_times') | join(', ') }}
            Avg charge price: €{{ state_attr('sensor.cew_today', 'avg_cheap_price') | round(3) }}/kWh

            Discharging at: {{ state_attr('sensor.cew_today', 'expensive_times') | join(', ') }}
            Avg discharge price: €{{ state_attr('sensor.cew_today', 'avg_expensive_price') | round(3) }}/kWh

            Spread: {{ state_attr('sensor.cew_today', 'spread_percentage') }}%
            Net profit potential: €{{ (state_attr('sensor.cew_today', 'avg_expensive_price') - state_attr('sensor.cew_today', 'avg_cheap_price')) | round(3) }}/kWh
```

### Important Notes

⚠️ **Safety First**: Always test your battery control automations carefully:
- Start with low power values
- Monitor the first few cycles manually
- Ensure your battery BMS has proper protections
- Check that charge/discharge commands work correctly

💡 **Customization**: Every battery system is different. The examples above are templates - you MUST adapt them to your specific battery controller's entities and requirements.

🔔 **Notifications**: Keep notification actions even after adding battery control - they help you monitor that everything is working as expected.

## Sensor Attributes

### sensor.cew_today

- `cheapest_times`: List of charging window times
- `cheapest_prices`: Corresponding prices for charging windows
- `expensive_times`: List of discharge window times
- `expensive_prices`: Corresponding prices for discharge windows
- `expensive_times_aggressive`: Aggressive discharge windows
- `expensive_prices_aggressive`: Prices for aggressive discharge
- `spread_avg`: Average spread percentage
- `spread_met`: Whether minimum spread requirement is met
- `current_price`: Current electricity price
- `avg_cheap_price`: Average price of cheap windows
- `avg_expensive_price`: Average price of expensive windows
- `completed_charge_windows`: Number of completed charge windows today
- `completed_discharge_windows`: Number of completed discharge windows
- `completed_charge_cost`: Total cost of charging today
- `completed_discharge_revenue`: Total revenue from discharging today

## Dashboard Features

### CEW Control Dashboard

- **Status Overview**: Current state, price, and spread information
- **Window Configuration**: Adjust window counts and percentiles
- **Spread Settings**: Configure minimum spreads for profitability
- **Cost Settings**: VAT, tax, and additional costs
- **Battery Settings**: Power limits and efficiency
- **Tomorrow Settings**: Configure different parameters for tomorrow
- **Time Overrides**: Force charging/discharging during specific periods
- **Notifications**: Configure alerts for state changes
- **Analytics**: View windows, statistics, and price analysis

## Troubleshooting

### No Windows Detected

1. Check that your price sensor is providing data
2. Verify percentile settings aren't too restrictive
3. Ensure minimum spread isn't set too high
4. Check if price override is active

### Tomorrow Sensor Shows "Unavailable"

This is normal. Tomorrow's prices typically become available between 13:00-14:00 (varies by provider).

### Settings Not Rotating at Midnight

1. Ensure "Tomorrow Settings Enabled" is turned on
2. Check that automation is enabled
3. Verify Home Assistant time zone is correct

## Performance

The integration uses an optimized calculation engine that:
- Caches results for 14 minutes 59 seconds
- Uses NumPy for efficient array operations
- Only recalculates when prices or settings change
- Typical calculation time: <100ms (vs 500-1000ms for YAML templates)

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Home Assistant Community for inspiration and support
- Nordpool integration for price data structure
- All contributors and testers

## Support

For issues, questions, or suggestions:
- Open an issue on [GitHub](https://github.com/cew-hacs/cheapest_energy_windows/issues)
- Join the discussion on [Home Assistant Community](https://community.home-assistant.io/)

## Changelog

### Version 1.0.0
- Initial release
- Full feature parity with YAML package
- HACS compatible structure
- Performance optimizations
- Comprehensive dashboard