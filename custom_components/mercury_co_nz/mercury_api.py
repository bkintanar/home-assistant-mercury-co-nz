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

    async def get_weekly_summary(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get weekly summary data from Mercury Energy using pymercury."""
        _LOGGER.debug("Getting weekly summary data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for weekly summary, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting weekly summary data using pymercury...")

            # Get account information first
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)

            if not complete_data:
                _LOGGER.error("No account data available for weekly summary")
                return {}

            # Extract required IDs
            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            # Find electricity service
            electricity_service = None
            for service in complete_data.services:
                if service.is_electricity:
                    electricity_service = service
                    break

            if not electricity_service:
                _LOGGER.error("No electricity service found for weekly summary")
                return {}

            service_id = electricity_service.service_id

            if not customer_id or not account_id or not service_id:
                _LOGGER.error("Missing required IDs for weekly summary")
                return {}

            _LOGGER.info("Using pymercury get_electricity_summary for weekly data: customer:%s, account:%s, service:%s",
                        customer_id, account_id, service_id)

            # Use pymercury's built-in get_electricity_summary method to get both weekly and monthly
            electricity_summary = await loop.run_in_executor(
                None,
                self._client._api_client.get_electricity_summary,
                customer_id, account_id, service_id
            )

            if not electricity_summary:
                _LOGGER.error("No electricity summary data returned for weekly")
                return {}

            _LOGGER.info("Successfully retrieved electricity summary for weekly data")
            _LOGGER.debug("Raw summary data for weekly: %s", electricity_summary)

            # Normalize the weekly summary data using pymercury's ElectricitySummary object
            normalized_weekly = self._normalize_weekly_summary_data(electricity_summary)
            _LOGGER.debug("Normalized weekly summary data: %s", normalized_weekly)
            return normalized_weekly

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

    async def get_monthly_summary(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get monthly summary data from Mercury Energy using pymercury."""
        _LOGGER.debug("Getting monthly summary data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for monthly summary, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting monthly summary data using pymercury...")

            # Get account information first
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)

            if not complete_data:
                _LOGGER.error("No account data available for monthly summary")
                return {}

            # Extract required IDs
            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            # Find electricity service
            electricity_service = None
            for service in complete_data.services:
                if service.is_electricity:
                    electricity_service = service
                    break

            if not electricity_service:
                _LOGGER.error("No electricity service found for monthly summary")
                return {}

            service_id = electricity_service.service_id

            if not customer_id or not account_id or not service_id:
                _LOGGER.error("Missing required IDs for monthly summary")
                return {}

            _LOGGER.info("Using pymercury get_electricity_summary for customer:%s, account:%s, service:%s",
                        customer_id, account_id, service_id)

            # Use pymercury's built-in get_electricity_summary method
            # This method automatically handles the asOfDate parameter (defaults to today)
            electricity_summary = await loop.run_in_executor(
                None,
                self._client._api_client.get_electricity_summary,
                customer_id, account_id, service_id
            )

            if not electricity_summary:
                _LOGGER.error("No electricity summary data returned")
                return {}

            _LOGGER.info("Successfully retrieved electricity summary")
            _LOGGER.debug("Raw summary data: %s", electricity_summary)

            # Normalize the summary data using pymercury's ElectricitySummary object
            normalized_summary = self._normalize_electricity_summary_data(electricity_summary)
            _LOGGER.debug("Normalized summary data: %s", normalized_summary)
            return normalized_summary

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

    async def get_usage_data(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get comprehensive usage data from Mercury Energy using ElectricityUsage."""
        _LOGGER.debug("Getting usage data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("Getting electricity usage data...")

            # Get account information first
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)

            if not complete_data:
                _LOGGER.error("❌ No account data available")
                return {}

            # Extract required IDs
            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            # Find electricity service
            electricity_service = None
            for service in complete_data.services:
                if service.is_electricity:
                    electricity_service = service
                    break

            if not electricity_service:
                _LOGGER.error("❌ No electricity service found")
                return {}

            service_id = electricity_service.service_id
            _LOGGER.info("🔍 Using IDs: customer_id=%s, account_id=%s, service_id=%s",
                        customer_id, account_id, service_id)

            # Get electricity usage data (default period - Mercury API determines the range)
            _LOGGER.info("📅 Requesting electricity usage data with default parameters")

            electricity_usage = await loop.run_in_executor(
                None,
                self._client._api_client.get_electricity_usage,
                customer_id, account_id, service_id
            )

            if not electricity_usage:
                _LOGGER.error("❌ No electricity usage data returned from get_electricity_usage API call")
                _LOGGER.error("❌ This could indicate:")
                _LOGGER.error("   - Authentication issues")
                _LOGGER.error("   - Account has no electricity service")
                _LOGGER.error("   - Mercury API is experiencing issues")
                _LOGGER.error("   - Customer ID, Account ID, or Service ID are incorrect")
                _LOGGER.error("❌ Returning empty usage data - sensors will show 0 values")
                return {}

            _LOGGER.info("✅ Received ElectricityUsage: %s data points, %.2f kWh total",
                        electricity_usage.data_points, electricity_usage.total_usage)

            # 🔍 DEBUG: Log how many days Mercury API actually provides
            if electricity_usage.daily_usage:
                _LOGGER.info("🔍 Mercury API provided %d daily entries:", len(electricity_usage.daily_usage))
                _LOGGER.info("   📅 First day: %s", electricity_usage.daily_usage[0].get('date', 'N/A'))
                _LOGGER.info("   📅 Last day: %s", electricity_usage.daily_usage[-1].get('date', 'N/A'))
                _LOGGER.info("   📅 Usage period: %s", electricity_usage.usage_period)
                _LOGGER.info("   📅 Days in period: %s", electricity_usage.days_in_period)

                        # Process ElectricityUsage object into normalized data
            normalized_data = self._process_electricity_usage(electricity_usage)

            # Get hourly usage data
            hourly_result = await self._execute_api_call_with_fallback(
                self._client._api_client.get_electricity_usage_hourly,
                customer_id, account_id, service_id,
                "hourly_usage", "hourly_usage_history",
                "Getting hourly electricity usage...",
                "Hourly usage: %.2f kWh (%d data points, %d history entries)",
                "Could not get hourly usage: %s"
            )
            normalized_data.update(hourly_result)

            # Get monthly usage data
            monthly_result = await self._execute_api_call_with_fallback(
                self._client._api_client.get_electricity_usage_monthly,
                customer_id, account_id, service_id,
                "monthly_usage", "monthly_usage_history",
                "Getting monthly electricity usage for extended history...",
                "Monthly usage: %.2f kWh (%d data points, %d monthly billing periods)",
                "Could not get monthly usage: %s"
            )
            normalized_data.update(monthly_result)

            # Add customer info
            normalized_data["customer_id"] = customer_id

            # Set current timestamp
            from datetime import datetime
            normalized_data["last_updated"] = datetime.now().isoformat()

            _LOGGER.info("✅ All electricity usage data retrieved: %s", {k: v for k, v in normalized_data.items() if k not in ['daily_usage_history', 'temperature_history', 'hourly_usage_history', 'monthly_usage_history']})
            return normalized_data

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
