# Cheapest Energy Windows v1.0.1

Bug fixes and improvements to state sensor calculations, dashboard templates, and documentation.

## 🐛 Bug Fixes

**State Sensor Calculations**
- ✅ Charging windows can now be set to **0** (discharge-only mode)
- ✅ Fixed discharge window selection when charge windows = 0
- ✅ Fixed net kWh calculations to show negative values when discharge > charge
- ✅ Fixed net price calculation for profit scenarios

**Example**: Discharge 5 windows while charging only 2 now correctly shows negative net kWh and profit calculations

## 📊 Dashboard Improvements

- Updated all battery activity calculations
- Fixed net cost/price displays for profit scenarios
- All dashboard cards now handle negative values correctly

## 📚 Documentation Updates

**README.md Major Improvements**
- Added comprehensive window duration (15-min vs 1-hour) documentation
- Completely rewrote Dashboard Installation section with accurate steps
- Massively expanded Automation System documentation with examples
- Fixed Performance section (5 second updates, <10ms calculations)
- Added Table of Contents

## 📦 Upgrade Instructions

1. Update via HACS or manually replace files
2. Restart Home Assistant
3. **Refresh your browser** to load updated dashboard templates

## ⚠️ Breaking Changes

None - Fully backward compatible with v1.0.0

---

**Full Changelog**: https://github.com/cew-hacs/cheapest_energy_windows/compare/v1.0.0...v1.0.1
