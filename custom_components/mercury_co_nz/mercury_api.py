"""Mercury Energy API client wrapper."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import DECIMAL_PLACES, TEMP_DECIMAL_PLACES, FALLBACK_ZERO, FALLBACK_EMPTY_LIST

_LOGGER = logging.getLogger(__name__)

try:
    from pymercury import MercuryClient
    PYMERCURY_AVAILABLE = True
    _LOGGER.info("pymercury with MercuryClient available")
except ImportError as e:
    _LOGGER.warning("pymercury MercuryClient not available: %s", e)
    _LOGGER.info("Using fallback implementation")
    PYMERCURY_AVAILABLE = False

    # pymercury not available - integration will fail gracefully
    class MercuryClient:
        def __init__(self, email, password):
            raise ImportError("pymercury library is required but not available")


class MercuryAPI:
    """Mercury Energy API client wrapper."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        """Initialize the API client."""
        self._session = session
        self._email = email
        self._password = password
        self._client = None
        self._authenticated = False

    async def authenticate(self) -> bool:
        """Authenticate with Mercury Energy using pymercury library."""
        if self._authenticated and self._client and self._client.is_logged_in:
            _LOGGER.debug("Already authenticated")
            return True

        try:
            _LOGGER.info("Authenticating with Mercury Energy...")

            loop = asyncio.get_event_loop()

            # Initialize MercuryClient using pymercury
            self._client = await loop.run_in_executor(
                None, MercuryClient, self._email, self._password
            )

            # Use client's login method (which handles OAuth internally)
            _LOGGER.debug("Calling client login...")
            tokens = await loop.run_in_executor(None, self._client.login)

            if tokens:
                _LOGGER.debug("Got login tokens: %s", type(tokens).__name__)

            # Check if login was successful
            if self._client.is_logged_in:
                self._authenticated = True
                _LOGGER.info("Successfully authenticated with Mercury Energy")
                _LOGGER.info("Customer ID: %s", getattr(self._client, 'customer_id', 'Unknown'))
                _LOGGER.info("Account IDs: %s", getattr(self._client, 'account_ids', 'Unknown'))
                return True
            else:
                _LOGGER.error("Authentication failed - not logged in")
                self._authenticated = False
                return False

        except Exception as exc:
            _LOGGER.error("Authentication failed: %s", exc, exc_info=True)
            self._authenticated = False
            return False

    async def get_weekly_summary(self, _retry_count: int = 0) -> dict[str, dict[str, Any]]:
        """Get weekly summary data per electricity ICP (v2.0.0 multi-ICP).

        Returns {service_id: per_service_dict}. Empty dict if no electricity services.
        """
        _LOGGER.debug("Getting weekly summary data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for weekly summary, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting weekly summary data (multi-ICP)...")

            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)
            if not complete_data:
                _LOGGER.error("No account data available for weekly summary")
                return {}

            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None
            if not customer_id or not account_id:
                _LOGGER.error("Missing customer_id or account_id for weekly summary")
                return {}

            electricity_services = [s for s in complete_data.services if s.is_electricity]
            if not electricity_services:
                _LOGGER.error("No electricity services found for weekly summary")
                return {}

            per_service: dict[str, dict[str, Any]] = {}
            for service in electricity_services:
                service_id = service.service_id
                _LOGGER.info("Weekly summary for service_id=%s", service_id)

                electricity_summary = await loop.run_in_executor(
                    None,
                    self._client._api_client.get_electricity_summary,
                    customer_id, account_id, service_id,
                )
                if not electricity_summary:
                    _LOGGER.warning("No weekly summary returned for service_id=%s", service_id)
                    continue

                normalized = self._normalize_weekly_summary_data(electricity_summary)
                if normalized:
                    per_service[service_id] = normalized

            return per_service

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("Tokens expired during weekly summary, attempting re-authentication...")
                self._authenticated = False
                success = await self.authenticate()
                if success:
                    _LOGGER.info("Re-authentication successful, retrying weekly summary...")
                    return await self.get_weekly_summary(_retry_count + 1)
                else:
                    _LOGGER.error("Re-authentication failed for weekly summary")
                    return {}
            else:
                _LOGGER.error("Error fetching weekly summary data: %s", exc, exc_info=True)
                return {}

    def _normalize_weekly_summary_data(self, electricity_summary: Any) -> dict[str, Any]:
        """Normalize weekly summary data from pymercury's ElectricitySummary object."""
        if not electricity_summary:
            return {}

        try:
            # Access the raw data from the ElectricitySummary object
            if hasattr(electricity_summary, 'raw_data'):
                summary_dict = electricity_summary.raw_data
            elif hasattr(electricity_summary, '__dict__'):
                summary_dict = electricity_summary.__dict__
            else:
                summary_dict = electricity_summary

            # Extract weekly summary information from the API response
            weekly_summary = summary_dict.get("weeklySummary", {})

            if not weekly_summary:
                _LOGGER.warning("No weekly summary data found in API response")
                return {}

            normalized = {
                "start_date": weekly_summary.get("startDate", ""),
                "end_date": weekly_summary.get("endDate", ""),
                "usage_cost": float(weekly_summary.get("lastWeekCost", 0)),
                "notes": weekly_summary.get("notes", []),
                "usage_history": weekly_summary.get("usage", []),
            }

            _LOGGER.info("Normalized weekly summary data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("Error normalizing weekly summary data: %s", exc)
            return {}

    async def get_monthly_summary(self, _retry_count: int = 0) -> dict[str, dict[str, Any]]:
        """Get monthly summary data per electricity ICP (v2.0.0 multi-ICP)."""
        _LOGGER.debug("Getting monthly summary data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for monthly summary, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting monthly summary data (multi-ICP)...")

            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)
            if not complete_data:
                _LOGGER.error("No account data available for monthly summary")
                return {}

            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None
            if not customer_id or not account_id:
                _LOGGER.error("Missing customer_id or account_id for monthly summary")
                return {}

            electricity_services = [s for s in complete_data.services if s.is_electricity]
            if not electricity_services:
                _LOGGER.error("No electricity services found for monthly summary")
                return {}

            per_service: dict[str, dict[str, Any]] = {}
            for service in electricity_services:
                service_id = service.service_id
                _LOGGER.info("Monthly summary for service_id=%s", service_id)

                electricity_summary = await loop.run_in_executor(
                    None,
                    self._client._api_client.get_electricity_summary,
                    customer_id, account_id, service_id,
                )
                if not electricity_summary:
                    _LOGGER.warning("No monthly summary returned for service_id=%s", service_id)
                    continue

                normalized = self._normalize_electricity_summary_data(electricity_summary)
                if normalized:
                    per_service[service_id] = normalized

            return per_service

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("Tokens expired during monthly summary, attempting re-authentication...")
                self._authenticated = False
                success = await self.authenticate()
                if success:
                    _LOGGER.info("Re-authentication successful, retrying monthly summary...")
                    return await self.get_monthly_summary(_retry_count + 1)
                else:
                    _LOGGER.error("Re-authentication failed for monthly summary")
                    return {}
            else:
                _LOGGER.error("Error fetching monthly summary data: %s", exc, exc_info=True)
                return {}

    def _normalize_electricity_summary_data(self, electricity_summary: Any) -> dict[str, Any]:
        """Normalize electricity summary data from pymercury's ElectricitySummary object."""
        if not electricity_summary:
            return {}

        try:
            # Access the raw data from the ElectricitySummary object
            if hasattr(electricity_summary, 'raw_data'):
                summary_dict = electricity_summary.raw_data
            elif hasattr(electricity_summary, '__dict__'):
                summary_dict = electricity_summary.__dict__
            else:
                summary_dict = electricity_summary

            # Extract monthly summary information from the API response
            monthly_summary = summary_dict.get("monthlySummary", {})

            normalized = {
                "billing_start_date": monthly_summary.get("startDate", ""),
                "billing_end_date": monthly_summary.get("endDate", ""),
                "billing_status": monthly_summary.get("status", ""),
                "days_remaining": monthly_summary.get("daysRemaining", 0),
                "usage_cost": float(monthly_summary.get("usageCost", 0)),
                "usage_consumption": float(monthly_summary.get("usageConsumption", 0)),
                "projected_bill_note": monthly_summary.get("note", ""),
            }

            # Calculate billing period progress
            if monthly_summary.get("startDate") and monthly_summary.get("endDate"):
                from datetime import datetime
                try:
                    start_date = datetime.fromisoformat(monthly_summary["startDate"].replace('Z', '+00:00'))
                    end_date = datetime.fromisoformat(monthly_summary["endDate"].replace('Z', '+00:00'))
                    now = datetime.now(start_date.tzinfo)

                    total_days = (end_date - start_date).days
                    elapsed_days = (now - start_date).days

                    if total_days > 0:
                        progress_percent = min(100, max(0, (elapsed_days / total_days) * 100))
                        normalized["billing_progress_percent"] = round(progress_percent, 1)
                    else:
                        normalized["billing_progress_percent"] = 0

                except Exception as date_err:
                    _LOGGER.warning("Could not calculate billing progress: %s", date_err)
                    normalized["billing_progress_percent"] = 0

            _LOGGER.info("Normalized electricity summary data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("Error normalizing electricity summary data: %s", exc)
            return {}

    async def get_bill_summary(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get bill summary data from Mercury Energy."""
        _LOGGER.debug("Getting bill summary data (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for bill summary")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting bill summary data...")

            # Get account information
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)
            if not complete_data:
                _LOGGER.error("No account data available")
                return {}

            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            if not customer_id or not account_id:
                _LOGGER.error("Missing customer_id or account_id")
                return {}

            # Try to get bill summary using pymercury
            try:
                if hasattr(self._client, '_api_client') and hasattr(self._client._api_client, 'get_bill_summary'):
                    bill_summary = await loop.run_in_executor(
                        None,
                        lambda: self._client._api_client.get_bill_summary(customer_id, account_id)
                    )
                else:
                    _LOGGER.warning("Bill summary method not available in pymercury")
                    return {}
            except Exception as api_err:
                _LOGGER.error("Error calling bill summary API: %s", api_err)
                return {}

            if not bill_summary:
                _LOGGER.warning("No bill summary data returned")
                return {}

            _LOGGER.info("Successfully retrieved bill summary")
            return self._normalize_bill_data(bill_summary)

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("Tokens expired, re-authenticating...")
                self._authenticated = False
                if await self.authenticate():
                    return await self.get_bill_summary(_retry_count + 1)

            _LOGGER.error("Error fetching bill summary: %s", exc, exc_info=True)
            return {}

    def _normalize_bill_data(self, bill_data: Any) -> dict[str, Any]:
        """Normalize bill summary data to a consistent format."""
        if not bill_data:
            return {}

        try:
            # Convert to dict if needed
            if hasattr(bill_data, '__dict__'):
                bill_dict = bill_data.__dict__
            elif hasattr(bill_data, 'to_dict'):
                bill_dict = bill_data.to_dict()
            else:
                bill_dict = bill_data

            # Use the correct field names from the BillSummary object
            normalized = {
                "account_id": bill_dict.get("account_id", ""),
                "balance": float(bill_dict.get("current_balance", 0)) if bill_dict.get("current_balance") else 0,
                "due_amount": float(bill_dict.get("due_amount", 0)) if bill_dict.get("due_amount") else 0,
                "bill_date": bill_dict.get("bill_date", ""),
                "due_date": bill_dict.get("due_date", ""),
                "overdue_amount": float(bill_dict.get("overdue_amount", 0)) if bill_dict.get("overdue_amount") else 0,
                "payment_type": bill_dict.get("payment_type", ""),
                "payment_method": bill_dict.get("payment_method", ""),
                "bill_url": bill_dict.get("bill_url", ""),
                "balance_status": bill_dict.get("balance_status", ""),
            }

            # Process statement details - use direct fields from BillSummary
            normalized["statement_total"] = float(bill_dict.get("statement_total", 0)) if bill_dict.get("statement_total") else 0

            # Use direct amount fields from BillSummary object
            normalized["electricity_amount"] = float(bill_dict.get("electricity_amount", 0)) if bill_dict.get("electricity_amount") else 0
            normalized["gas_amount"] = float(bill_dict.get("gas_amount", 0)) if bill_dict.get("gas_amount") else 0
            normalized["broadband_amount"] = float(bill_dict.get("broadband_amount", 0)) if bill_dict.get("broadband_amount") else 0

            # Store statement details as-is
            normalized["statement_details"] = bill_dict.get("statement_details", [])

            _LOGGER.debug("Normalized bill data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("Error normalizing bill data: %s", exc)
            return {}

    async def get_electricity_plans(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get electricity plan / current rate data from Mercury Energy.

        Issue #6 — exposes the per-kWh rate so HACS dynamic_energy_cost can compute
        per-appliance costs in real time. Mirrors the get_bill_summary shape but
        also extracts service_id (the rates endpoint is per-ICP, not per-account).
        """
        _LOGGER.debug("Getting electricity plans data (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for electricity plans")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting electricity plans data (multi-ICP)...")

            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)
            if not complete_data:
                _LOGGER.error("No account data available")
                return {}

            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None
            if not customer_id or not account_id:
                _LOGGER.error("Missing customer_id or account_id")
                return {}

            electricity_services = [s for s in complete_data.services if s.is_electricity]
            if not electricity_services:
                _LOGGER.error("No electricity services found for plans data")
                return {}

            per_service: dict[str, dict[str, Any]] = {}

            for electricity_service in electricity_services:
                service_id = electricity_service.service_id
                _LOGGER.info(
                    "Mercury plans: fetching for service_id=%s, service_group=%s",
                    service_id,
                    getattr(electricity_service, 'service_group', '?'),
                )

                try:
                    if hasattr(self._client, '_api_client') and hasattr(self._client._api_client, 'get_electricity_plans'):
                        plans = await loop.run_in_executor(
                            None,
                            lambda sid=service_id: self._client._api_client.get_electricity_plans(customer_id, account_id, sid),
                        )
                    else:
                        _LOGGER.warning("Electricity plans method not available in pymercury")
                        continue
                except Exception as api_err:
                    _LOGGER.error(
                        "Error calling electricity plans API for service_id=%s: %s",
                        service_id, api_err,
                    )
                    continue

                if not plans:
                    _LOGGER.warning(
                        "No electricity plans data returned for service_id=%s",
                        service_id,
                    )
                    continue

                normalized = self._normalize_plans_data(plans)
                if normalized:
                    per_service[service_id] = normalized

            return per_service

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("Tokens expired, re-authenticating...")
                self._authenticated = False
                if await self.authenticate():
                    return await self.get_electricity_plans(_retry_count + 1)

            _LOGGER.error("Error fetching electricity plans: %s", exc, exc_info=True)
            return {}

    @staticmethod
    def _parse_rate_amount(value: Any, measure: str | None = None) -> float | None:
        """Parse a Mercury rate value into a float in NZD per the unit (kWh/day).

        Mercury's /electricity/plans endpoint returns rates as DISPLAY-FORMATTED
        strings with a currency prefix — e.g. ``'$0.2737'`` for dollars-per-kWh,
        or ``'27.37c'`` if Mercury ever serves a cents-form (defensive). Other
        endpoints (bill, weekly, monthly) return numeric values, so this helper
        lives only in the plans-data normalization path.

        Args:
            value: Mercury's rate value (string, int, float, or None).
            measure: The companion rate_measure string (e.g. ``'$/kWh'``,
                ``'c/kWh'``, or empty). Used to decide cents-to-dollars.

        Returns:
            Float in NZD per (kWh / day) — i.e. dollars, never cents.
            ``None`` if the input is missing or unparseable.
        """
        if value is None:
            return None

        # If pymercury ever returns a numeric type, treat it as already
        # canonical dollars. The current Mercury API delivers strings; this
        # branch is defensive for future format changes.
        has_dollar_prefix = False
        if isinstance(value, (int, float)):
            numeric = float(value)
        else:
            raw_str = str(value).strip()
            # Track the $ prefix BEFORE stripping it — the value's own currency
            # symbol is a stronger signal than the `measure` field. If the
            # value says dollars and the measure says cents, the value wins.
            has_dollar_prefix = raw_str.startswith("$")
            cleaned = (
                raw_str
                .replace("$", "")
                .replace(",", "")
                .rstrip("c")
            )
            try:
                numeric = float(cleaned)
            except ValueError:
                _LOGGER.warning(
                    "Mercury plans: could not parse rate %r (measure=%r); returning None",
                    value, measure,
                )
                return None

        # Cents -> dollars only if the measure explicitly says cents AND the
        # value itself wasn't dollar-prefixed. Mercury actually returns dollars
        # today; the cents branch is defensive for future format variation.
        if (
            not has_dollar_prefix
            and measure
            and "c" in measure.lower()
            and "$" not in measure
        ):
            numeric = numeric / 100.0

        return round(numeric, 6)

    def _normalize_plans_data(self, plans_data: Any) -> dict[str, Any]:
        """Normalize ElectricityPlans data to a flat dict.

        Mercury's /electricity/plans endpoint serves rates as DISPLAY-FORMATTED
        strings — typically '$0.2737' (dollars-per-kWh) for anytime_rate and
        '$X.XX' for daily_fixed_charge. The `_parse_rate_amount` helper handles
        the string -> float conversion and uses the rate_measure field to
        disambiguate cents/dollars defensively.
        """
        if not plans_data:
            return {}

        try:
            # Convert to dict if needed
            if hasattr(plans_data, '__dict__'):
                plans_dict = plans_data.__dict__
            elif hasattr(plans_data, 'to_dict'):
                plans_dict = plans_data.to_dict()
            else:
                plans_dict = plans_data

            anytime_raw = plans_dict.get("anytime_rate")
            daily_raw = plans_dict.get("daily_fixed_charge")
            anytime_measure = plans_dict.get("anytime_rate_measure")
            # Mercury doesn't expose a separate measure for daily_fixed_charge
            # in pymercury's model; it's per-day in dollars. Pass None.

            normalized = {
                # Numeric (NZD)
                "anytime_rate": self._parse_rate_amount(anytime_raw, anytime_measure),
                "daily_fixed_charge": self._parse_rate_amount(daily_raw, None),
                # Text
                "current_plan_id": plans_dict.get("current_plan_id") or "",
                "current_plan_name": plans_dict.get("current_plan_name") or "",
                "current_plan_description": plans_dict.get("current_plan_description") or "",
                "current_plan_usage_type": plans_dict.get("current_plan_usage_type") or "",
                "icp_number": plans_dict.get("icp_number") or "",
                "anytime_rate_measure": plans_dict.get("anytime_rate_measure") or "",
                "plan_change_date": plans_dict.get("plan_change_date") or "",
                # Booleans serialized as text (sensor-only platform)
                "can_change_plan": "yes" if plans_dict.get("can_change_plan") else "no",
                "is_pending_plan_change": "yes" if plans_dict.get("is_pending_plan_change") else "no",
            }

            _LOGGER.debug("Normalized plans data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("Error normalizing electricity plans data: %s", exc)
            return {}


    async def _execute_api_call_with_fallback(self, api_method, customer_id, account_id, service_id,
                                            usage_key, history_key, log_message, success_message, error_message):
        """Helper method for API calls with fallback handling."""
        loop = asyncio.get_event_loop()

        try:
            _LOGGER.info(log_message)
            result = await loop.run_in_executor(
                None,
                api_method,
                customer_id, account_id, service_id
            )

            if result:
                usage_value = round(result.total_usage, DECIMAL_PLACES)
                history_data = getattr(result, 'daily_usage', FALLBACK_EMPTY_LIST) or FALLBACK_EMPTY_LIST

                # Special handling for monthly data
                if 'monthly' in history_key:
                    history_data = self._extract_monthly_usage_data(result)
                    if not history_data and hasattr(result, 'daily_usage') and result.daily_usage:
                        _LOGGER.warning("Monthly data extraction failed, using daily data. Count: %d", len(result.daily_usage))
                        history_data = result.daily_usage

                data_points = getattr(result, 'data_points', 0)
                history_count = len(history_data)

                _LOGGER.info(success_message, result.total_usage, data_points, history_count)

                return {
                    usage_key: usage_value,
                    history_key: history_data
                }
            else:
                return {
                    usage_key: FALLBACK_ZERO,
                    history_key: FALLBACK_EMPTY_LIST
                }

        except Exception as e:
            _LOGGER.warning(error_message, e)
            return {
                usage_key: FALLBACK_ZERO,
                history_key: FALLBACK_EMPTY_LIST
            }

    async def get_usage_content(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get electricity usage content from Mercury Energy including disclaimers."""
        _LOGGER.debug("Getting usage content... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for usage content, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting electricity usage content using pymercury...")

            # Use pymercury's built-in get_electricity_usage_content method
            usage_content = await loop.run_in_executor(
                None,
                self._client._api_client.get_electricity_usage_content
            )

            if not usage_content:
                _LOGGER.error("No electricity usage content returned")
                return {}

            _LOGGER.info("Successfully retrieved electricity usage content")
            _LOGGER.debug("Raw usage content: %s", usage_content)

            # Normalize the usage content data
            normalized_content = self._normalize_usage_content_data(usage_content)
            _LOGGER.debug("Normalized usage content: %s", normalized_content)
            return normalized_content

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("Tokens expired during usage content, attempting re-authentication...")
                self._authenticated = False
                success = await self.authenticate()
                if success:
                    _LOGGER.info("Re-authentication successful, retrying usage content...")
                    return await self.get_usage_content(_retry_count + 1)
                else:
                    _LOGGER.error("❌ Re-authentication failed for usage content")
                    return {}
            else:
                _LOGGER.error("❌ Error fetching usage content: %s", exc, exc_info=True)
                return {}

    def _normalize_usage_content_data(self, usage_content: Any) -> dict[str, Any]:
        """Normalize usage content data from pymercury's ElectricityUsageContent object."""
        if not usage_content:
            return {}

        try:
            # Access the raw data from the ElectricityUsageContent object
            if hasattr(usage_content, 'raw_data'):
                content_dict = usage_content.raw_data
            elif hasattr(usage_content, '__dict__'):
                content_dict = usage_content.__dict__
            else:
                content_dict = usage_content

            # Extract disclaimer text from content structure
            content_data = content_dict.get("content", {})
            disclaimer_usage_summary = content_data.get("disclaimer_usage_summary", {})

            normalized = {
                "disclaimer_text": disclaimer_usage_summary.get("text", ""),
                "monthly_summary_description": content_data.get("monthly_summary_description", {}).get("text", ""),
                "monthly_summary_info": content_data.get("monthly_summary_info_modal_body", {}).get("text", ""),
            }

            _LOGGER.debug("✅ Normalized usage content data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("❌ Error normalizing usage content data: %s", exc)
            return {}

    async def get_usage_data(self, _retry_count: int = 0) -> dict[str, dict[str, Any]]:
        """Get usage data per electricity ICP (v2.0.0 multi-ICP).

        Returns {service_id: per_service_dict} keyed by electricity service_id.
        Each per-service dict has the same keys as v1.5.x's flat return
        (total_usage, energy_usage, current_bill, daily_usage_history, etc.)
        — only the OUTER dict shape changes.

        Empty dict if no electricity services found.
        """
        _LOGGER.debug("Getting usage data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting electricity usage data (multi-ICP)...")

            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)
            if not complete_data:
                _LOGGER.error("❌ No account data available")
                return {}

            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            electricity_services = [s for s in complete_data.services if s.is_electricity]
            if not electricity_services:
                _LOGGER.error("❌ No electricity services found")
                return {}

            _LOGGER.info(
                "🔍 Iterating %d electricity service(s): %s",
                len(electricity_services),
                [s.service_id for s in electricity_services],
            )

            per_service: dict[str, dict[str, Any]] = {}

            for service in electricity_services:
                service_id = service.service_id
                _LOGGER.info("📅 Fetching electricity usage for service_id=%s", service_id)

                electricity_usage = await loop.run_in_executor(
                    None,
                    self._client._api_client.get_electricity_usage,
                    customer_id, account_id, service_id,
                )

                if not electricity_usage:
                    _LOGGER.warning(
                        "⚠️ No usage data returned for service_id=%s — skipping this ICP",
                        service_id,
                    )
                    continue

                _LOGGER.info(
                    "✅ ICP %s: %s data points, %.2f kWh total",
                    service_id, electricity_usage.data_points, electricity_usage.total_usage,
                )

                normalized_data = self._process_electricity_usage(electricity_usage)

                hourly_result = await self._execute_api_call_with_fallback(
                    self._client._api_client.get_electricity_usage_hourly,
                    customer_id, account_id, service_id,
                    "hourly_usage", "hourly_usage_history",
                    f"Getting hourly usage for ICP {service_id}...",
                    "Hourly usage: %.2f kWh (%d data points, %d history entries)",
                    "Could not get hourly usage: %s",
                )
                normalized_data.update(hourly_result)

                monthly_result = await self._execute_api_call_with_fallback(
                    self._client._api_client.get_electricity_usage_monthly,
                    customer_id, account_id, service_id,
                    "monthly_usage", "monthly_usage_history",
                    f"Getting monthly usage for ICP {service_id}...",
                    "Monthly usage: %.2f kWh (%d data points, %d monthly billing periods)",
                    "Could not get monthly usage: %s",
                )
                normalized_data.update(monthly_result)

                normalized_data["customer_id"] = customer_id
                from datetime import datetime
                normalized_data["last_updated"] = datetime.now().isoformat()

                per_service[service_id] = normalized_data

            _LOGGER.info(
                "✅ Multi-ICP fetch complete: %d service(s) populated",
                len(per_service),
            )
            return per_service

        except Exception as exc:
            # Check if it's a token expiration error and we haven't already retried
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("🔄 Tokens expired, attempting re-authentication...")
                self._authenticated = False  # Reset authentication flag

                # Try to re-authenticate
                success = await self.authenticate()
                if success:
                    _LOGGER.info("✅ Re-authentication successful, retrying data fetch...")
                    # Retry the data fetch once (increment retry count to prevent infinite loop)
                    return await self.get_usage_data(_retry_count + 1)
                else:
                    _LOGGER.error("❌ Re-authentication failed")
                    return {}
            else:
                _LOGGER.error("❌ Error fetching electricity usage data: %s", exc, exc_info=True)
                return {}

    async def get_gas_usage_data(self) -> dict[str, Any]:
        """Fetch monthly gas usage from Mercury (v1.4.0).

        Mercury's gas API only returns useful data at interval='monthly'.
        pymercury exposes get_gas_usage(interval='daily') and
        get_gas_usage_hourly but Mercury responds with empty `usage` arrays
        for both — confirmed via maintainer testing — so we only call
        get_gas_usage_monthly.

        Returns a dict whose keys the coordinator will prefix with `gas_`
        before merging into `combined_data`. The statistics importer reads
        `gas_monthly_usage_history` and emits one StatisticData entry per
        Mercury invoice period.
        """
        try:
            loop = asyncio.get_event_loop()
            complete_data = await loop.run_in_executor(
                None, self._client.get_complete_account_data
            )
            if not complete_data:
                return {}

            account_id = (
                complete_data.account_ids[0] if complete_data.account_ids else None
            )

            gas_services = [s for s in complete_data.services if s.is_gas]
            if not gas_services:
                _LOGGER.debug("No gas services found; skipping gas usage fetch")
                return {}

            customer_id = complete_data.customer_id
            per_service: dict[str, dict[str, Any]] = {}

            for gas_service in gas_services:
                service_id = gas_service.service_id
                _LOGGER.info(
                    "Mercury gas: fetching monthly usage for service_id=%s",
                    service_id,
                )

                gas_monthly = await loop.run_in_executor(
                    None,
                    self._client._api_client.get_gas_usage_monthly,
                    customer_id, account_id, service_id,
                )

                if not gas_monthly:
                    _LOGGER.warning(
                        "Mercury get_gas_usage_monthly returned None for service_id=%s",
                        service_id,
                    )
                    continue

                monthly_history = list(getattr(gas_monthly, "daily_usage", []) or [])

                _LOGGER.info(
                    "Mercury gas (ICP %s): %d monthly entries, %.2f kWh total, $%.2f total",
                    service_id,
                    len(monthly_history),
                    getattr(gas_monthly, "total_usage", 0) or 0,
                    getattr(gas_monthly, "total_cost", 0) or 0,
                )

                per_service[service_id] = {
                    "monthly_usage": round(float(getattr(gas_monthly, "total_usage", 0) or 0), DECIMAL_PLACES),
                    "monthly_cost": round(float(getattr(gas_monthly, "total_cost", 0) or 0), DECIMAL_PLACES),
                    "monthly_data_points": getattr(gas_monthly, "data_points", 0),
                    "monthly_usage_history": monthly_history,
                    "service_id": service_id,
                }

            return per_service
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error("Mercury gas usage fetch failed: %s", exc, exc_info=True)
            return {}

    def _process_electricity_usage(self, usage: Any) -> dict[str, Any]:
        """Process ElectricityUsage object into normalized sensor data."""
        normalized_data = {}

        try:
            # Basic usage statistics
            normalized_data["total_usage"] = round(usage.total_usage, DECIMAL_PLACES)
            normalized_data["energy_usage"] = round(usage.average_daily_usage, DECIMAL_PLACES)
            normalized_data["current_bill"] = round(usage.total_cost, DECIMAL_PLACES)

            # Get latest day's data
            if usage.daily_usage:
                latest_day = usage.daily_usage[-1]
                normalized_data["latest_daily_usage"] = latest_day.get('consumption', FALLBACK_ZERO)
                normalized_data["latest_daily_cost"] = latest_day.get('cost', FALLBACK_ZERO)
            else:
                normalized_data["latest_daily_usage"] = FALLBACK_ZERO
                normalized_data["latest_daily_cost"] = FALLBACK_ZERO

            # Temperature data
            if usage.average_temperature is not None:
                normalized_data["average_temperature"] = round(usage.average_temperature, TEMP_DECIMAL_PLACES)
            else:
                normalized_data["average_temperature"] = FALLBACK_ZERO

            # Current temperature (from latest temperature reading)
            if usage.temperature_data:
                latest_temp = usage.temperature_data[-1]
                normalized_data["current_temperature"] = latest_temp.get('temp', FALLBACK_ZERO)
            else:
                normalized_data["current_temperature"] = FALLBACK_ZERO

            # Store detailed data for graph cards
            normalized_data["daily_usage_history"] = usage.daily_usage if usage.daily_usage else FALLBACK_EMPTY_LIST
            normalized_data["temperature_history"] = usage.temperature_data if usage.temperature_data else FALLBACK_EMPTY_LIST

            _LOGGER.debug("Processed ElectricityUsage: %s kWh total, %s days",
                         usage.total_usage, usage.data_points)

        except Exception as e:
            _LOGGER.error("Error processing ElectricityUsage: %s", e, exc_info=True)

        return normalized_data



    def _process_usage_response(self, usage_data: Any, normalized_data: dict) -> None:
        """Process usage data response from pymercury."""
        if usage_data and isinstance(usage_data, dict):
            # Extract data based on actual Mercury API response structure
            usage_records = usage_data.get('usage', [])
            if usage_records and len(usage_records) > 0:
                daily_data = usage_records[0].get('data', [])

                if daily_data:
                    # Calculate totals and averages
                    total_consumption = sum(day.get('consumption', 0) for day in daily_data)
                    total_cost = sum(day.get('cost', 0) for day in daily_data)
                    average_daily_consumption = total_consumption / len(daily_data) if daily_data else 0

                    # Get latest day's data
                    latest_day = daily_data[-1] if daily_data else {}

                    # Set normalized data
                    normalized_data["total_usage"] = round(total_consumption, 2)
                    normalized_data["energy_usage"] = round(average_daily_consumption, 2)
                    normalized_data["current_bill"] = round(total_cost, 2)
                    normalized_data["latest_daily_usage"] = latest_day.get('consumption', 0)
                    normalized_data["latest_daily_cost"] = latest_day.get('cost', 0)

                    # Store detailed data for attributes
                    normalized_data["daily_usage_history"] = daily_data

                    _LOGGER.info("Processed %d days of usage data", len(daily_data))

            # Process temperature data
            temperature_data = usage_data.get('averageTemperature', {}).get('data', [])
            if temperature_data:
                latest_temp = temperature_data[-1].get('temp', 0) if temperature_data else 0
                avg_temp = sum(day.get('temp', 0) for day in temperature_data) / len(temperature_data) if temperature_data else 0

                normalized_data["average_temperature"] = round(avg_temp, 1)
                normalized_data["current_temperature"] = latest_temp
                normalized_data["temperature_history"] = temperature_data

                _LOGGER.info("Processed temperature data: avg=%.1f°C, current=%d°C", avg_temp, latest_temp)

    def _process_complete_data(self, complete_data: dict, normalized_data: dict):
        """Process the complete account data from pymercury."""
        _LOGGER.debug("Processing complete account data...")

        try:
            # The complete_data structure may contain multiple accounts and services
            # We need to explore the structure to find usage data

            if isinstance(complete_data, dict):
                # Log the structure to understand it better
                _LOGGER.info("📋 Complete data keys: %s", list(complete_data.keys()))

                # Try to find usage data in various possible locations
                usage_found = False

                # Look for usage data in the structure
                if 'usage' in complete_data:
                    self._process_usage_response(complete_data, normalized_data)
                    usage_found = True
                elif 'accounts' in complete_data:
                    # Process accounts array
                    for account in complete_data.get('accounts', []):
                        if 'usage' in account:
                            self._process_usage_response(account, normalized_data)
                            usage_found = True
                            break

                # If no specific usage structure found, try to extract any meaningful data
                if not usage_found:
                    _LOGGER.info("🔍 No standard usage structure found, exploring data...")

                    # Extract any customer information
                    if 'customer' in complete_data:
                        customer = complete_data['customer']
                        if 'id' in customer:
                            normalized_data["customer_id"] = customer['id']

                    # No fallback data extraction - use only real API data

        except Exception as e:
            _LOGGER.error("Error processing complete account data: %s", e, exc_info=True)
            # No sample data - let sensors show unavailable if API fails





    def _extract_monthly_usage_data(self, monthly_usage):
        """Extract proper monthly usage data from the dedicated monthly endpoint."""
        try:
            # Check if this is a pymercury ElectricityUsage object with usage_data
            if hasattr(monthly_usage, 'usage_data') and monthly_usage.usage_data:
                usage_data = monthly_usage.usage_data

                # Check if usage_data is directly the list of monthly billing periods
                if isinstance(usage_data, list) and len(usage_data) > 0:
                    # Check if it looks like monthly billing data (has invoiceFrom/invoiceTo)
                    first_entry = usage_data[0]
                    if isinstance(first_entry, dict) and 'invoiceFrom' in first_entry and 'invoiceTo' in first_entry:
                        return usage_data

                # Fallback: Check if usage_data has nested structure
                if isinstance(usage_data, dict) and 'usage' in usage_data:
                    usage_array = usage_data['usage']
                    if usage_array and len(usage_array) > 0:
                        actual_usage = next((u for u in usage_array if u.get('label') == 'actual'), usage_array[0])
                        if 'data' in actual_usage:
                            return actual_usage['data']

            # Try other possible data locations
            for attr_name in ['raw_data', 'data']:
                if hasattr(monthly_usage, attr_name):
                    raw_data = getattr(monthly_usage, attr_name)
                    if isinstance(raw_data, dict) and 'usage' in raw_data:
                        usage_array = raw_data['usage']
                        if usage_array and len(usage_array) > 0:
                            actual_usage = next((u for u in usage_array if u.get('label') == 'actual'), usage_array[0])
                            if 'data' in actual_usage:
                                return actual_usage['data']

            # Check if monthly_usage itself is the raw dict structure
            if isinstance(monthly_usage, dict) and 'usage' in monthly_usage:
                usage_array = monthly_usage['usage']
                if usage_array and len(usage_array) > 0:
                    actual_usage = next((u for u in usage_array if u.get('label') == 'actual'), usage_array[0])
                    if 'data' in actual_usage:
                        return actual_usage['data']

            return []

        except Exception as e:
            _LOGGER.error("Error extracting monthly usage data: %s", e)
            return []

    async def close(self) -> None:
        """Close the API client."""
        if self._client and hasattr(self._client, 'close'):
            await asyncio.get_event_loop().run_in_executor(None, self._client.close)
