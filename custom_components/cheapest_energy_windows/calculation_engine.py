"""Calculation engine for Cheapest Energy Windows."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from homeassistant.util import dt as dt_util

from .const import (
    LOGGER_NAME,
    PRICING_15_MINUTES,
    PRICING_1_HOUR,
    MODE_CHARGE,
    MODE_DISCHARGE,
    MODE_DISCHARGE_AGGRESSIVE,
    MODE_IDLE,
    STATE_CHARGE,
    STATE_DISCHARGE,
    STATE_DISCHARGE_AGGRESSIVE,
    STATE_IDLE,
    STATE_OFF,
)

_LOGGER = logging.getLogger(LOGGER_NAME)


class WindowCalculationEngine:
    """High-performance window selection engine."""

    def __init__(self) -> None:
        """Initialize the calculation engine."""
        pass

    def calculate_windows(
        self,
        raw_prices: List[Dict[str, Any]],
        config: Dict[str, Any],
        is_tomorrow: bool = False
    ) -> Dict[str, Any]:
        """Calculate optimal charging/discharging windows.

        Args:
            raw_prices: List of price data from NordPool or similar
            config: Configuration from input entities
            is_tomorrow: Whether calculating for tomorrow

        Returns:
            Dictionary with calculated windows and attributes
        """
        # Debug logging for calculation window
        _LOGGER.warning(f"=== CALCULATION ENGINE CALLED for {'tomorrow' if is_tomorrow else 'today'} ===")
        _LOGGER.warning(f"Config keys received: {list(config.keys())}")
        _LOGGER.warning(f"calculation_window_enabled in config: {config.get('calculation_window_enabled', 'NOT PRESENT')}")
        _LOGGER.warning(f"calculation_window_start: {config.get('calculation_window_start', 'NOT PRESENT')}")
        _LOGGER.warning(f"calculation_window_end: {config.get('calculation_window_end', 'NOT PRESENT')}")

        # Get configuration values
        pricing_mode = config.get("pricing_window_duration", PRICING_15_MINUTES)

        # Use tomorrow's config if applicable
        suffix = "_tomorrow" if is_tomorrow and config.get("tomorrow_settings_enabled", False) else ""

        num_charge_windows = int(config.get(f"charging_windows{suffix}", 4))
        num_discharge_windows = int(config.get(f"expensive_windows{suffix}", 4))
        cheap_percentile = config.get(f"cheap_percentile{suffix}", 25)
        expensive_percentile = config.get(f"expensive_percentile{suffix}", 25)
        min_spread = config.get(f"min_spread{suffix}", 10)
        min_spread_discharge = config.get(f"min_spread_discharge{suffix}", 20)
        aggressive_spread = config.get(f"aggressive_discharge_spread{suffix}", 40)
        min_price_diff = config.get(f"min_price_difference{suffix}", 0.05)

        # Cost calculations
        vat = config.get("vat", 0.21)
        tax = config.get("tax", 0.12286)
        additional_cost = config.get("additional_cost", 0.02398)

        # Process prices based on mode
        processed_prices = self._process_prices(
            raw_prices, pricing_mode, vat, tax, additional_cost
        )

        if not processed_prices:
            _LOGGER.warning("No prices to process")
            return self._empty_result(is_tomorrow)

        # Apply calculation window filter if enabled
        calc_window_enabled = config.get("calculation_window_enabled", False)
        if calc_window_enabled:
            calc_window_start = config.get("calculation_window_start", "00:00:00")
            calc_window_end = config.get("calculation_window_end", "23:59:59")
            _LOGGER.warning(f"Calculation window ENABLED: {calc_window_start} - {calc_window_end}, filtering {len(processed_prices)} prices")
            processed_prices = self._filter_prices_by_calculation_window(
                processed_prices,
                calc_window_start,
                calc_window_end
            )
            _LOGGER.warning(f"After calculation window filter: {len(processed_prices)} prices remain")
            if not processed_prices:
                _LOGGER.warning("No prices after calculation window filter")
                return self._empty_result(is_tomorrow)
        else:
            _LOGGER.debug("Calculation window disabled")

        # Find windows
        charge_windows = self._find_charge_windows(
            processed_prices,
            num_charge_windows,
            cheap_percentile,
            min_spread,
            min_price_diff
        )

        discharge_windows = self._find_discharge_windows(
            processed_prices,
            charge_windows,
            num_discharge_windows,
            expensive_percentile,
            min_spread_discharge,
            min_price_diff
        )

        aggressive_windows = self._find_aggressive_discharge_windows(
            processed_prices,
            charge_windows,
            discharge_windows,
            num_discharge_windows,
            expensive_percentile,
            aggressive_spread,
            min_price_diff
        )

        # Debug output when calculation window is enabled
        if calc_window_enabled:
            charge_times = [w["timestamp"].strftime("%H:%M") for w in charge_windows]
            discharge_times = [w["timestamp"].strftime("%H:%M") for w in discharge_windows]
            _LOGGER.warning(f"After calculation window filter - Charge windows: {charge_times}, Discharge windows: {discharge_times}")

        # Calculate current state
        current_state = self._determine_current_state(
            processed_prices,
            charge_windows,
            discharge_windows,
            aggressive_windows,
            config
        )

        # Build result
        result = self._build_result(
            processed_prices,
            charge_windows,
            discharge_windows,
            aggressive_windows,
            current_state,
            config,
            is_tomorrow
        )

        return result

    def _process_prices(
        self,
        raw_prices: List[Dict[str, Any]],
        pricing_mode: str,
        vat: float,
        tax: float,
        additional_cost: float
    ) -> List[Dict[str, Any]]:
        """Process raw prices with VAT, tax, and additional costs."""
        _LOGGER.info("="*60)
        _LOGGER.info("PROCESS PRICES START")
        _LOGGER.info(f"Raw prices type: {type(raw_prices)}")
        _LOGGER.info(f"Raw prices length: {len(raw_prices) if hasattr(raw_prices, '__len__') else 'N/A'}")
        _LOGGER.info(f"Pricing mode: {pricing_mode}")
        _LOGGER.info(f"VAT: {vat} (type: {type(vat)})")
        _LOGGER.info(f"Tax: {tax} (type: {type(tax)})")
        _LOGGER.info(f"Additional cost: {additional_cost} (type: {type(additional_cost)})")

        if raw_prices and len(raw_prices) > 0:
            _LOGGER.info(f"First item type: {type(raw_prices[0])}")
            _LOGGER.info(f"First item: {raw_prices[0]}")
            if len(raw_prices) > 1:
                _LOGGER.info(f"Second item: {raw_prices[1]}")

        processed = []

        if pricing_mode == PRICING_1_HOUR:
            # Group by hour and average
            hourly_prices = {}
            for item in raw_prices:
                try:
                    # Validate item is a dict
                    if not isinstance(item, dict):
                        _LOGGER.error(f"Item is not a dict! Type: {type(item)}, Value: {item}")
                        continue

                    # Parse timestamp - handle both datetime objects and strings
                    start_value = item.get("start")
                    if not start_value:
                        _LOGGER.warning(f"Item has no 'start' key: {item}")
                        continue

                    if isinstance(start_value, datetime):
                        # Already a datetime object (new Nordpool format)
                        timestamp = start_value
                    elif isinstance(start_value, str):
                        # String format (old format)
                        timestamp_str = start_value.replace('"', '')
                        timestamp = datetime.fromisoformat(timestamp_str)
                    else:
                        _LOGGER.error(f"Unexpected start type: {type(start_value)}, Value: {start_value}")
                        continue

                    hour = timestamp.replace(minute=0, second=0, microsecond=0)

                    if hour not in hourly_prices:
                        hourly_prices[hour] = []

                    # Calculate total price
                    base_price = item.get("value", 0)
                    total_price = (base_price * (1 + vat)) + tax + additional_cost
                    hourly_prices[hour].append(total_price)

                except (ValueError, TypeError, AttributeError) as e:
                    _LOGGER.error(f"Failed to process price item: {e}", exc_info=True)
                    _LOGGER.error(f"Problematic item: {item}")
                    continue

            # Average hourly prices
            for hour, prices in hourly_prices.items():
                if prices:
                    processed.append({
                        "timestamp": hour,
                        "price": float(np.mean(prices)),  # Convert numpy.float64 to Python float
                        "duration": 60  # 60 minutes
                    })

        else:  # 15-minute mode
            for item in raw_prices:
                try:
                    # Validate item is a dict
                    if not isinstance(item, dict):
                        _LOGGER.error(f"Item is not a dict! Type: {type(item)}, Value: {item}")
                        continue

                    # Parse timestamp - handle both datetime objects and strings
                    start_value = item.get("start")
                    if not start_value:
                        _LOGGER.warning(f"Item has no 'start' key: {item}")
                        continue

                    if isinstance(start_value, datetime):
                        # Already a datetime object (new Nordpool format)
                        timestamp = start_value
                    elif isinstance(start_value, str):
                        # String format (old format)
                        timestamp_str = start_value.replace('"', '')
                        timestamp = datetime.fromisoformat(timestamp_str)
                    else:
                        _LOGGER.error(f"Unexpected start type: {type(start_value)}, Value: {start_value}")
                        continue

                    base_price = item.get("value", 0)
                    total_price = (base_price * (1 + vat)) + tax + additional_cost

                    processed.append({
                        "timestamp": timestamp,
                        "price": total_price,
                        "duration": 15  # 15 minutes
                    })

                except (ValueError, TypeError, AttributeError) as e:
                    _LOGGER.error(f"Failed to process price item: {e}", exc_info=True)
                    _LOGGER.error(f"Problematic item: {item}")
                    continue

        # Sort by timestamp
        processed.sort(key=lambda x: x["timestamp"])

        _LOGGER.info(f"Processed {len(processed)} price entries")
        if processed:
            _LOGGER.info(f"First processed price: {processed[0]}")
            _LOGGER.info(f"Last processed price: {processed[-1]}")
        _LOGGER.info("PROCESS PRICES END")
        _LOGGER.info("="*60)

        return processed

    def _filter_prices_by_calculation_window(
        self,
        prices: List[Dict[str, Any]],
        start_str: str,
        end_str: str
    ) -> List[Dict[str, Any]]:
        """Filter prices to only include those within the calculation window time range.

        This restricts the price analysis to a specific time window each day.
        For example, if you only want to charge/discharge between 06:00-22:00,
        set the calculation window to those times.
        """
        if not prices:
            return prices

        filtered = []

        try:
            # Parse time strings (HH:MM:SS format)
            start_parts = start_str.split(":")
            end_parts = end_str.split(":")

            start_hour = int(start_parts[0])
            start_minute = int(start_parts[1])
            end_hour = int(end_parts[0])
            end_minute = int(end_parts[1])

            for price_data in prices:
                timestamp = price_data["timestamp"]
                price_hour = timestamp.hour
                price_minute = timestamp.minute

                # Convert to minutes since midnight for easier comparison
                price_time = price_hour * 60 + price_minute
                start_time = start_hour * 60 + start_minute
                end_time = end_hour * 60 + end_minute

                # Handle overnight periods
                if end_time < start_time:
                    # Overnight: include if time >= start OR time < end
                    if price_time >= start_time or price_time < end_time:
                        filtered.append(price_data)
                else:
                    # Same day: include if start <= time < end
                    if start_time <= price_time < end_time:
                        filtered.append(price_data)

            _LOGGER.info(f"Calculation window filter: {len(prices)} -> {len(filtered)} prices (window: {start_str} to {end_str})")

        except (ValueError, IndexError, AttributeError) as e:
            _LOGGER.error(f"Failed to parse calculation window times: {e}")
            return prices  # Return unfiltered on error

        return filtered

    def _find_charge_windows(
        self,
        prices: List[Dict[str, Any]],
        num_windows: int,
        cheap_percentile: float,
        min_spread: float,
        min_price_diff: float
    ) -> List[Dict[str, Any]]:
        """Find cheapest windows for charging."""
        if not prices or num_windows <= 0:
            return []

        # Convert to numpy array for efficient operations
        price_array = np.array([p["price"] for p in prices])

        # Calculate percentile threshold
        cheap_threshold = np.percentile(price_array, cheap_percentile)

        # Get candidates below threshold
        candidates = []
        for i, price_data in enumerate(prices):
            if price_data["price"] <= cheap_threshold:
                candidates.append({
                    "index": i,
                    "timestamp": price_data["timestamp"],
                    "price": price_data["price"],
                    "duration": price_data["duration"]
                })

        # Sort by price
        candidates.sort(key=lambda x: x["price"])

        # Progressive selection with spread check
        selected = []
        expensive_avg = np.mean(price_array[price_array > np.percentile(price_array, 100 - cheap_percentile)])

        for candidate in candidates:
            if len(selected) >= num_windows:
                break

            # Test spread with this window
            test_prices = [s["price"] for s in selected] + [candidate["price"]]
            cheap_avg = np.mean(test_prices)

            # Calculate spread percentage
            if cheap_avg > 0:
                spread_pct = ((expensive_avg - cheap_avg) / cheap_avg) * 100
                price_diff = expensive_avg - cheap_avg

                if spread_pct >= min_spread and price_diff >= min_price_diff:
                    selected.append(candidate)

        return selected

    def _find_discharge_windows(
        self,
        prices: List[Dict[str, Any]],
        charge_windows: List[Dict[str, Any]],
        num_windows: int,
        expensive_percentile: float,
        min_spread: float,
        min_price_diff: float
    ) -> List[Dict[str, Any]]:
        """Find expensive windows for discharging."""
        if not prices or num_windows <= 0:
            return []

        # Exclude charging times
        charge_indices = {w["index"] for w in charge_windows}

        # Filter out charging windows
        available_prices = []
        for i, price_data in enumerate(prices):
            if i not in charge_indices:
                available_prices.append({
                    "index": i,
                    "timestamp": price_data["timestamp"],
                    "price": price_data["price"],
                    "duration": price_data["duration"]
                })

        if not available_prices:
            return []

        # Convert to numpy array
        price_array = np.array([p["price"] for p in available_prices])

        # Calculate percentile threshold
        expensive_threshold = np.percentile(price_array, 100 - expensive_percentile)

        # Get candidates above threshold
        candidates = []
        for price_data in available_prices:
            if price_data["price"] >= expensive_threshold:
                candidates.append(price_data)

        # Sort by price (descending for discharge)
        candidates.sort(key=lambda x: x["price"], reverse=True)

        # Progressive selection with spread check
        selected = []
        if charge_windows:
            cheap_avg = np.mean([w["price"] for w in charge_windows])
        else:
            cheap_avg = np.mean(price_array[price_array < np.percentile(price_array, expensive_percentile)])

        for candidate in candidates:
            if len(selected) >= num_windows:
                break

            # If no charge windows, skip spread check and just select top expensive windows
            if not charge_windows:
                selected.append(candidate)
                continue

            # Test spread with this window
            test_prices = [s["price"] for s in selected] + [candidate["price"]]
            expensive_avg = np.mean(test_prices)

            # Calculate spread percentage
            if cheap_avg > 0:
                spread_pct = ((expensive_avg - cheap_avg) / cheap_avg) * 100
                price_diff = expensive_avg - cheap_avg

                if spread_pct >= min_spread and price_diff >= min_price_diff:
                    selected.append(candidate)

        return selected

    def _find_aggressive_discharge_windows(
        self,
        prices: List[Dict[str, Any]],
        charge_windows: List[Dict[str, Any]],
        discharge_windows: List[Dict[str, Any]],
        num_windows: int,
        expensive_percentile: float,
        aggressive_spread: float,
        min_price_diff: float
    ) -> List[Dict[str, Any]]:
        """Find windows for aggressive discharge (peak prices)."""
        if not prices or num_windows <= 0:
            return []

        # Use discharge windows as base, filter by aggressive spread
        candidates = []

        if charge_windows:
            cheap_avg = np.mean([w["price"] for w in charge_windows])
        else:
            price_array = np.array([p["price"] for p in prices])
            cheap_avg = np.mean(price_array[price_array < np.percentile(price_array, expensive_percentile)])

        for window in discharge_windows:
            if cheap_avg > 0:
                spread_pct = ((window["price"] - cheap_avg) / cheap_avg) * 100
                price_diff = window["price"] - cheap_avg

                if spread_pct >= aggressive_spread and price_diff >= min_price_diff:
                    candidates.append(window)

        return candidates

    def _determine_current_state(
        self,
        prices: List[Dict[str, Any]],
        charge_windows: List[Dict[str, Any]],
        discharge_windows: List[Dict[str, Any]],
        aggressive_windows: List[Dict[str, Any]],
        config: Dict[str, Any]
    ) -> str:
        """Determine current state based on time and configuration."""
        # Check if automation is enabled
        if not config.get("automation_enabled", True):
            return STATE_OFF

        now = dt_util.now()
        current_time = now.replace(second=0, microsecond=0)

        # Check time override
        if config.get("time_override_enabled", False):
            start_str = config.get("time_override_start", "")
            end_str = config.get("time_override_end", "")
            mode = config.get("time_override_mode", MODE_IDLE)

            if self._is_in_time_range(current_time, start_str, end_str):
                return self._mode_to_state(mode)

        # Check price override
        if config.get("price_override_enabled", False):
            threshold = config.get("price_override_threshold", 0.15)
            current_price = self._get_current_price(prices, current_time)
            if current_price and current_price <= threshold:
                return STATE_CHARGE

        # Check scheduled windows
        for window in aggressive_windows:
            if self._is_window_active(window, current_time):
                return STATE_DISCHARGE_AGGRESSIVE

        for window in discharge_windows:
            if self._is_window_active(window, current_time):
                return STATE_DISCHARGE

        for window in charge_windows:
            if self._is_window_active(window, current_time):
                return STATE_CHARGE

        return STATE_IDLE

    def _is_window_active(self, window: Dict[str, Any], current_time: datetime) -> bool:
        """Check if a window is currently active."""
        window_time = window["timestamp"]
        window_duration = window["duration"]

        # Check if current time falls within the window
        window_start = window_time
        window_end = window_time + timedelta(minutes=window_duration)

        return window_start <= current_time < window_end

    def _is_in_time_range(self, current_time: datetime, start_str: str, end_str: str) -> bool:
        """Check if current time is within a time range."""
        try:
            # Parse time strings (HH:MM:SS format)
            start_parts = start_str.split(":")
            end_parts = end_str.split(":")

            start_time = current_time.replace(
                hour=int(start_parts[0]),
                minute=int(start_parts[1]),
                second=0
            )
            end_time = current_time.replace(
                hour=int(end_parts[0]),
                minute=int(end_parts[1]),
                second=0
            )

            # Handle overnight periods
            if end_time < start_time:
                return current_time >= start_time or current_time < end_time
            else:
                return start_time <= current_time < end_time

        except (ValueError, IndexError, AttributeError):
            return False

    def _get_current_price(
        self, prices: List[Dict[str, Any]], current_time: datetime
    ) -> Optional[float]:
        """Get the current price."""
        for price_data in prices:
            if self._is_window_active(price_data, current_time):
                return price_data["price"]
        return None

    def _mode_to_state(self, mode: str) -> str:
        """Convert override mode to state."""
        mode_map = {
            MODE_IDLE: STATE_IDLE,
            MODE_CHARGE: STATE_CHARGE,
            MODE_DISCHARGE: STATE_DISCHARGE,
            MODE_DISCHARGE_AGGRESSIVE: STATE_DISCHARGE_AGGRESSIVE,
        }
        return mode_map.get(mode, STATE_IDLE)

    def _calculate_actual_windows(
        self,
        prices: List[Dict[str, Any]],
        charge_windows: List[Dict[str, Any]],
        discharge_windows: List[Dict[str, Any]],
        aggressive_windows: List[Dict[str, Any]],
        config: Dict[str, Any],
        is_tomorrow: bool = False
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Calculate actual charge/discharge windows considering time and price overrides.

        This shows what the battery will ACTUALLY do when overrides are applied.
        For example:
        - Time override: if 8:00-10:00 is calculated as charge, but 9:00-10:00 has a
          discharge override, the actual charge window will only be 8:00-9:00.
        - Price override: if price drops below threshold, those periods become charge windows
          even if not in calculated windows.

        Args:
            prices: List of processed price data
            charge_windows: Calculated charge windows
            discharge_windows: Calculated discharge windows
            aggressive_windows: Calculated aggressive discharge windows
            config: Configuration dictionary
            is_tomorrow: Whether calculating for tomorrow (affects config key suffix)

        Returns:
            Tuple of (actual_charge_windows, actual_discharge_windows)
        """
        # Use tomorrow's config if applicable
        suffix = "_tomorrow" if is_tomorrow and config.get("tomorrow_settings_enabled", False) else ""

        # Check if any override is enabled
        time_override_enabled = config.get(f"time_override_enabled{suffix}", False)
        price_override_enabled = config.get(f"price_override_enabled{suffix}", False)

        if not time_override_enabled and not price_override_enabled:
            # No overrides, return calculated windows as-is (don't combine normal + aggressive)
            return list(charge_windows), list(discharge_windows)

        # Get override configuration (using suffix for tomorrow settings)
        override_start_str = config.get(f"time_override_start{suffix}", "")
        override_end_str = config.get(f"time_override_end{suffix}", "")
        override_mode = config.get(f"time_override_mode{suffix}", MODE_IDLE)
        price_override_threshold = config.get(f"price_override_threshold{suffix}", 0.15)

        # Validate time override config if enabled
        if time_override_enabled and (not override_start_str or not override_end_str):
            # Invalid time override config, disable it
            time_override_enabled = False

        # Build a complete timeline of all price windows with their states
        # considering calculated windows, time overrides, and price overrides
        timeline = []

        for price_data in prices:
            timestamp = price_data["timestamp"]
            duration = price_data["duration"]
            price = price_data["price"]

            # Determine state for this time period (priority order: time override > price override > calculated)
            state = STATE_IDLE  # Default

            # Check time override first (highest priority)
            if time_override_enabled and self._is_in_time_range(timestamp, override_start_str, override_end_str):
                state = self._mode_to_state(override_mode)
            # Check price override
            elif price_override_enabled and price <= price_override_threshold:
                state = STATE_CHARGE
            else:
                # Check calculated windows
                for window in aggressive_windows:
                    if self._is_window_active(window, timestamp):
                        state = STATE_DISCHARGE_AGGRESSIVE
                        break

                if state == STATE_IDLE:
                    for window in discharge_windows:
                        if self._is_window_active(window, timestamp):
                            state = STATE_DISCHARGE
                            break

                if state == STATE_IDLE:
                    for window in charge_windows:
                        if self._is_window_active(window, timestamp):
                            state = STATE_CHARGE
                            break

            timeline.append({
                "timestamp": timestamp,
                "price": price_data["price"],
                "duration": duration,
                "state": state
            })

        # Extract actual charge and discharge windows from timeline
        new_actual_charge = [w for w in timeline if w["state"] == STATE_CHARGE]
        new_actual_discharge = [w for w in timeline if w["state"] in [STATE_DISCHARGE, STATE_DISCHARGE_AGGRESSIVE]]

        return new_actual_charge, new_actual_discharge

    def _build_result(
        self,
        prices: List[Dict[str, Any]],
        charge_windows: List[Dict[str, Any]],
        discharge_windows: List[Dict[str, Any]],
        aggressive_windows: List[Dict[str, Any]],
        current_state: str,
        config: Dict[str, Any],
        is_tomorrow: bool
    ) -> Dict[str, Any]:
        """Build the result dictionary with all attributes."""
        now = dt_util.now()
        current_time = now.replace(second=0, microsecond=0)
        current_price = self._get_current_price(prices, current_time)

        # Calculate averages
        cheap_prices = [w["price"] for w in charge_windows]
        expensive_prices = [w["price"] for w in discharge_windows]

        avg_cheap = float(np.mean(cheap_prices)) if cheap_prices else 0.0
        avg_expensive = float(np.mean(expensive_prices)) if expensive_prices else 0.0

        # Calculate spreads
        spread_pct = 0.0
        if avg_cheap > 0 and avg_expensive > 0:
            spread_pct = float(((avg_expensive - avg_cheap) / avg_cheap) * 100)

        # Calculate actual windows considering time and price overrides
        actual_charge, actual_discharge = self._calculate_actual_windows(
            prices,
            charge_windows,
            discharge_windows,
            aggressive_windows,
            config,
            is_tomorrow
        )

        # Count completed windows (use actual windows to include price/time overrides)
        completed_charge = sum(
            1 for w in actual_charge
            if w["timestamp"] + timedelta(minutes=w["duration"]) <= current_time
        )
        completed_discharge = sum(
            1 for w in actual_discharge
            if w["timestamp"] + timedelta(minutes=w["duration"]) <= current_time
        )

        # Calculate costs (use actual windows to include price/time overrides)
        charge_power = config.get("charge_power", 2400) / 1000  # Convert to kW
        discharge_power = config.get("discharge_power", 2400) / 1000

        completed_charge_cost = sum(
            w["price"] * (w["duration"] / 60) * charge_power
            for w in actual_charge
            if w["timestamp"] + timedelta(minutes=w["duration"]) <= current_time
        )

        completed_discharge_revenue = sum(
            w["price"] * (w["duration"] / 60) * discharge_power
            for w in actual_discharge
            if w["timestamp"] + timedelta(minutes=w["duration"]) <= current_time
        )

        # Build result
        result = {
            "state": current_state,
            "cheapest_times": [w["timestamp"].isoformat() for w in charge_windows],
            "cheapest_prices": [float(w["price"]) for w in charge_windows],
            "expensive_times": [w["timestamp"].isoformat() for w in discharge_windows],
            "expensive_prices": [float(w["price"]) for w in discharge_windows],
            "expensive_times_aggressive": [w["timestamp"].isoformat() for w in aggressive_windows],
            "expensive_prices_aggressive": [float(w["price"]) for w in aggressive_windows],
            "actual_charge_times": [w["timestamp"].isoformat() for w in actual_charge],
            "actual_charge_prices": [float(w["price"]) for w in actual_charge],
            "actual_discharge_times": [w["timestamp"].isoformat() for w in actual_discharge],
            "actual_discharge_prices": [float(w["price"]) for w in actual_discharge],
            "completed_charge_windows": completed_charge,
            "completed_discharge_windows": completed_discharge,
            "completed_charge_cost": round(completed_charge_cost, 3),
            "completed_discharge_revenue": round(completed_discharge_revenue, 3),
            "num_windows": len(charge_windows),
            "min_spread_required": config.get("min_spread", 10),
            "spread_percentage": round(spread_pct, 1),
            "spread_met": bool(spread_pct >= config.get("min_spread", 10)),
            "spread_avg": round(spread_pct, 1),
            "actual_spread_avg": round(spread_pct, 1),
            "discharge_spread_met": bool(spread_pct >= config.get("min_spread_discharge", 20)),
            "aggressive_discharge_spread_met": bool(spread_pct >= config.get("aggressive_discharge_spread", 40)),
            "avg_cheap_price": round(avg_cheap, 5),
            "avg_expensive_price": round(avg_expensive, 5),
            "current_price": round(current_price, 5) if current_price else 0,
            "price_override_active": config.get("price_override_enabled", False) and
                                    current_price and
                                    current_price <= config.get("price_override_threshold", 0.15),
            "time_override_active": config.get("time_override_enabled", False),
            "automation_enabled": config.get("automation_enabled", True),
            "calculation_window_enabled": config.get("calculation_window_enabled", False),
        }

        return result

    def _empty_result(self, is_tomorrow: bool) -> Dict[str, Any]:
        """Return an empty result structure."""
        return {
            "state": STATE_OFF,
            "cheapest_times": [],
            "cheapest_prices": [],
            "expensive_times": [],
            "expensive_prices": [],
            "expensive_times_aggressive": [],
            "expensive_prices_aggressive": [],
            "actual_charge_times": [],
            "actual_charge_prices": [],
            "actual_discharge_times": [],
            "actual_discharge_prices": [],
            "completed_charge_windows": 0,
            "completed_discharge_windows": 0,
            "completed_charge_cost": 0,
            "completed_discharge_revenue": 0,
            "num_windows": 0,
            "min_spread_required": 0,
            "spread_percentage": 0,
            "spread_met": False,
            "spread_avg": 0,
            "actual_spread_avg": 0,
            "discharge_spread_met": False,
            "aggressive_discharge_spread_met": False,
            "avg_cheap_price": 0,
            "avg_expensive_price": 0,
            "current_price": 0,
            "price_override_active": False,
            "time_override_active": False,
            "automation_enabled": False,
            "calculation_window_enabled": False,
        }