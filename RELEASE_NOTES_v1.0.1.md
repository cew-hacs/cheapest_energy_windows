# Cheapest Energy Windows v1.0.1

Bug fixes and improvements to state sensor calculations, dashboard templates, and documentation.

## 🐛 Bug Fixes

### State Sensor Calculations

**Fixed charging windows minimum constraint**
- Charging windows can now be set to **0** (discharge-only mode)
- Previously required minimum of 1 charging window
- Enables scenarios where you only sell energy without buying
- Files: `config_flow.py`, `number.py`

**Fixed discharge window selection with 0 charge windows**
- Discharge windows are now selected even when charging windows = 0
- Previously, spread validation prevented discharge-only operation
- System now skips spread check when no charge windows are configured
- File: `calculation_engine.py`

**Fixed net kWh calculations**
- Removed artificial discharge cap that limited `actual_discharged` to `usable_kwh`
- Net kWh can now show **negative values** when discharging more than charging
- Accurately represents scenarios where you use existing battery capacity
- Enables tracking when discharge > charge (common for profitable arbitrage)
- File: `main_dashboard.yaml` (8 instances fixed)

**Fixed net price calculation for profit scenarios**
- Net price now calculates correctly when `net_kwh` is negative
- Previously showed €0/kWh when making a profit
- Now shows effective price per kWh even in profit scenarios
- Formula changed from `if net_kwh > 0 else 0` to `if net_kwh != 0 else (avg_expensive - avg_cheap)`
- File: `main_dashboard.yaml`

### Example Scenario (Now Fixed)
**Before**: If you charge 2 windows but discharge 5 windows using existing battery:
- ❌ Dashboard showed: Net kWh = 0.0, Net Cost = €0.0
- ❌ Couldn't see actual discharge or profit

**After**: Same scenario now correctly shows:
- ✅ Net kWh = -3.2 kWh (negative = used existing battery)
- ✅ Net Cost = -€1.30 (negative = profit!)
- ✅ Net Price = €0.406/kWh (effective gain rate)

## 📊 Dashboard Improvements

**Updated calculations across all dashboard cards**
- Battery Activity (Today & Tomorrow)
- Daily Net Cost calculations
- Net kWh Available displays
- Net Price per kWh cards
- All calculations now handle negative values correctly
- File: `main_dashboard.yaml`

**Required Frontend Components** (no changes, documentation updated)
- Mushroom Cards
- fold-entity-row
- ApexCharts Card

## 📚 Documentation Updates

### README.md Major Improvements

**Window Duration Flexibility**
- Added prominent explanation of 15-minute vs 1-hour window options
- Clarified that users choose based on their energy contract
- Explained how Nord Pool 15-minute data is used or aggregated
- Added to Features section, Configuration section, and How It Works section

**Dashboard Installation Section**
- Completely rewritten with accurate installation steps
- Removed references to non-existent `install_dashboard` service
- Added direct download link to `main_dashboard.yaml`
- Clear instructions for manual dashboard installation
- Listed all required frontend components with HACS installation steps

**Automation System Documentation**
- Massive expansion of automation documentation
- Explained initial setup is **notification-only** (safe default)
- Added step-by-step guide for adding battery control actions
- Included 3 comprehensive automation examples:
  1. Simple switch control
  2. Mode-based control (Huawei, SolarEdge, etc.)
  3. Advanced time override integration
- Added safety warnings and best practices
- Included window attributes usage examples

**Performance Section**
- Corrected update interval: **5 seconds** (was incorrectly stated as ~15 minutes)
- Corrected calculation time: **<10ms** (was incorrectly stated as <100ms)
- Emphasized efficient handling of both 15-minute and 1-hour modes

**Other Improvements**
- Added Table of Contents for easy navigation
- Fixed dashboard preview image with cache-busting parameter
- Clarified Services section (removed non-existent services)
- Enhanced supported price sensors section

## 🔧 Technical Changes

**Files Modified:**
- `calculation_engine.py` - Discharge window selection logic
- `config_flow.py` - Charging windows minimum value
- `number.py` - Charging windows minimum value
- `main_dashboard.yaml` - Multiple calculation fixes
- `manifest.json` - Version bump to 1.0.1
- `README.md` - Comprehensive documentation improvements

## 📦 Installation

### New Installation
Install via HACS:
1. Add custom repository: `https://github.com/cew-hacs/cheapest_energy_windows`
2. Search for "Cheapest Energy Windows"
3. Click Download
4. Restart Home Assistant

### Upgrade from v1.0.0
1. **Via HACS**:
   - Go to HACS > Integrations
   - Find "Cheapest Energy Windows"
   - Click "Update"
   - Restart Home Assistant

2. **Manual**:
   - Replace the `custom_components/cheapest_energy_windows` folder
   - Restart Home Assistant

3. **After Update**:
   - If using the dashboard, **refresh your browser** to load updated templates
   - Check that charging windows minimum is now 0 (was 1)
   - Test discharge-only scenarios if applicable

## ⚠️ Breaking Changes

None - This release is fully backward compatible with v1.0.0

## 🎯 What's Next

Users can now:
- ✅ Run in discharge-only mode (0 charge windows)
- ✅ See accurate net kWh when discharging more than charging
- ✅ Track profits when discharge exceeds charge
- ✅ Better understand window duration options
- ✅ Follow improved documentation for automations

## 📝 Notes

- Dashboard refresh required after update to see template changes
- All existing configurations remain compatible
- No configuration changes needed after update

## 🙏 Credits

Thank you to all users who reported issues and provided feedback!

---

**Full Changelog**: https://github.com/cew-hacs/cheapest_energy_windows/compare/v1.0.0...v1.0.1
