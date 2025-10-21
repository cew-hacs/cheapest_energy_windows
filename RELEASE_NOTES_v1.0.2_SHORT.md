# Cheapest Energy Windows v1.0.2

Critical dashboard bug fixes for net price calculations and tomorrow's data handling.

## 🐛 Bug Fixes

**Dashboard Template Fixes**
- ✅ Fixed net price showing positive when making profit (now correctly shows negative)
- ✅ Fixed TypeError when tomorrow's Nord Pool data not available (before ~13:00)
- ✅ Net price formula now uses `(net_cost / (net_kwh | abs))` to preserve sign

**Example**: Discharging 5 windows while charging 2 now correctly shows **-€0.41/kWh** (profit) instead of **+€0.41/kWh** (cost)

## 📦 Upgrade Instructions

### Step 1: Update Integration
1. Update via HACS or manually replace files
2. Restart Home Assistant

### Step 2: Update Dashboard ⚠️ **REQUIRED**

**The dashboard MUST be reinstalled to get the bug fixes!**

**Quick Method:**
1. Go to your CEW dashboard → **⋮ menu** → **Edit Dashboard** → **⋮ menu** → **Raw configuration editor**
2. Download new [main_dashboard.yaml](https://github.com/cew-hacs/cheapest_energy_windows/blob/main/custom_components/cheapest_energy_windows/main_dashboard.yaml)
3. Replace ALL content with new YAML
4. Click **Save**
5. **Refresh your browser** (Ctrl+F5 or Cmd+Shift+R)

See full release notes for detailed instructions.

## ⚠️ Breaking Changes

None - Fully backward compatible

## 🎯 What's Fixed

✅ Profit scenarios now show negative net price
✅ No more TypeError before 13:00 when tomorrow's data loading
✅ Accurate cost/profit indicators

---

**Full Changelog**: https://github.com/cew-hacs/cheapest_energy_windows/compare/v1.0.1...v1.0.2
