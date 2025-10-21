# Cheapest Energy Windows v1.0.2

Critical dashboard bug fixes for net price calculations and tomorrow's data handling.

## 🐛 Bug Fixes

### Dashboard Template Fixes

**Fixed net price calculation showing incorrect sign**
- Net price now correctly shows **negative values for profit scenarios**
- Previously, when discharging more than charging, division of two negatives resulted in positive display
- Example: Discharging 5 windows while charging 2 windows now shows -€0.41/kWh (profit) instead of +€0.41/kWh (cost)
- Affects both "Battery Activity Today" and "Battery Activity Tomorrow" sections
- Formula changed from `(net_cost / net_kwh)` to `(net_cost / (net_kwh | abs))`
- File: `main_dashboard.yaml` (2 instances fixed)

**Fixed TypeError when tomorrow's data unavailable**
- Resolved "TypeError: object of type 'NoneType' has no len()" error
- Error occurred when tomorrow's Nord Pool data not yet available (before ~13:00-14:00 CET)
- Added proper None handling with `| default([])` filter
- Dashboard now gracefully displays 0 windows instead of error
- File: `main_dashboard.yaml`

## 📊 Impact

**Before these fixes:**
- ❌ Net price showed positive when making profit
- ❌ TypeError in Tomorrow's Settings section before 13:00
- ❌ Confusing display for profit scenarios

**After these fixes:**
- ✅ Net price correctly shows negative for profit (e.g., -€0.41/kWh)
- ✅ Net price correctly shows positive for cost (e.g., +€0.25/kWh)
- ✅ No errors when tomorrow's data unavailable
- ✅ Smooth user experience throughout the day

## 📦 Installation & Upgrade

### New Installation
Install via HACS:
1. Add custom repository: `https://github.com/cew-hacs/cheapest_energy_windows`
2. Search for "Cheapest Energy Windows"
3. Click Download
4. Restart Home Assistant
5. Install dashboard from `main_dashboard.yaml`

### Upgrade from v1.0.1 or v1.0.0

#### Step 1: Update Integration
1. **Via HACS**:
   - Go to HACS > Integrations
   - Find "Cheapest Energy Windows"
   - Click "Update"
   - Restart Home Assistant

2. **Manual**:
   - Replace the `custom_components/cheapest_energy_windows` folder
   - Restart Home Assistant

#### Step 2: Update Dashboard (REQUIRED)

⚠️ **IMPORTANT**: You MUST reinstall the dashboard to get the bug fixes!

**Option A: Fresh Install (Recommended)**
1. Go to **Settings > Dashboards**
2. Find your CEW dashboard
3. Click **⋮ menu** → **Delete** (this only removes the dashboard, not your data)
4. Create new dashboard following installation instructions in README
5. Copy contents from updated `main_dashboard.yaml`
6. **Refresh your browser** (Ctrl+F5 or Cmd+Shift+R)

**Option B: Manual Update**
1. Download the new `main_dashboard.yaml` from:
   - [Direct link](https://github.com/cew-hacs/cheapest_energy_windows/blob/main/custom_components/cheapest_energy_windows/main_dashboard.yaml)
   - Or find it locally at `/config/custom_components/cheapest_energy_windows/main_dashboard.yaml`
2. Go to your CEW dashboard
3. Click **⋮ menu** → **Edit Dashboard** → **⋮ menu** → **Raw configuration editor**
4. Replace ALL content with the new YAML
5. Click **Save**
6. **Refresh your browser** (Ctrl+F5 or Cmd+Shift+R)

> **Note**: Browser refresh is critical! Template changes won't appear without it.

## 🔧 Technical Details

**Files Modified:**
- `manifest.json` - Version bump to 1.0.2
- `main_dashboard.yaml` - 3 bug fixes applied

**Specific Changes:**
1. Line ~2004: Added `| abs` to net_kwh in Battery Activity Today
2. Line ~2170: Added `| abs` to net_kwh in Battery Activity Tomorrow
3. Line ~1153: Added `| default([])` to prevent TypeError

## ⚠️ Breaking Changes

None - Fully backward compatible with v1.0.1 and v1.0.0

## 🎯 Testing Scenarios

After updating, verify these scenarios work correctly:

**Profit Scenario (Discharge > Charge):**
- Set charging_windows = 0, expensive_windows = 4
- Check "Net Price" shows negative value (e.g., -€0.41/kWh)
- Verify "Net kWh Available" shows negative value (e.g., -2.4 kWh)

**Before 13:00 (Tomorrow Data Unavailable):**
- Check Tomorrow's Settings section
- Should show 0/0 windows gracefully
- No TypeError should appear

**Normal Operation:**
- Verify net price calculations match expectations
- Check profit/loss indicators show correct colors

## 📝 Notes

- Dashboard refresh required after update
- No configuration changes needed
- All existing settings preserved
- Integration code unchanged (only dashboard templates updated)

## 🙏 Credits

Thank you to users who reported these dashboard display issues!

---

**Full Changelog**: https://github.com/cew-hacs/cheapest_energy_windows/compare/v1.0.1...v1.0.2
