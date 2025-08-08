"""Mercury Energy API client wrapper."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# DRY Constants to eliminate magic numbers and repeated strings
class APIConstants:
    """Constants for API operations following DRY principles."""
    DECIMAL_PLACES = 2
    TEMP_DECIMAL_PLACES = 1
    FALLBACK_ZERO = 0
    FALLBACK_EMPTY_LIST = []

    # Consistent logging messages
    MSG_GETTING_HOURLY = "📊 Getting hourly electricity usage..."
    MSG_GETTING_MONTHLY = "📊 Getting monthly electricity usage for extended history..."
    MSG_SUCCESS_HOURLY = "✅ Hourly usage: %.2f kWh (%d data points, %d history entries)"
    MSG_SUCCESS_MONTHLY = "✅ Monthly usage: %.2f kWh (%d monthly billing periods)"
    MSG_ERROR_HOURLY = "⚠️ Could not get hourly usage: %s"
    MSG_ERROR_MONTHLY = "⚠️ Could not get monthly usage: %s"
    MSG_ERROR_EXTRACTION = "⚠️ Monthly data extraction failed! Falling back to daily_usage as temporary fix. Count: %d"

try:
    from pymercury import MercuryClient
    PYMERCURY_AVAILABLE = True
    _LOGGER.info("✅ pymercury with MercuryClient available")
except ImportError as e:
    _LOGGER.warning("⚠️ pymercury MercuryClient not available: %s", e)
    _LOGGER.info("💡 Using fallback implementation")
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
            _LOGGER.info("🔐 Authenticating with Mercury Energy...")

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
                _LOGGER.info("✅ Successfully authenticated with Mercury Energy")
                _LOGGER.info("Customer ID: %s", getattr(self._client, 'customer_id', 'Unknown'))
                _LOGGER.info("Account IDs: %s", getattr(self._client, 'account_ids', 'Unknown'))
                return True
            else:
                _LOGGER.error("❌ Authentication failed - not logged in")
                self._authenticated = False
                return False

        except Exception as exc:
            _LOGGER.error("❌ Authentication failed: %s", exc, exc_info=True)
            self._authenticated = False
            return False

    async def get_bill_summary(self, _retry_count: int = 0) -> dict[str, Any]:
        """Get bill summary data from Mercury Energy."""
        _LOGGER.error("🚨 GET_BILL_SUMMARY CALLED! retry_count=%d", _retry_count)
        _LOGGER.debug("Getting bill summary data... (retry count: %d)", _retry_count)

        if not self._authenticated or not self._client:
            _LOGGER.debug("Not authenticated, attempting authentication...")
            success = await self.authenticate()
            if not success:
                _LOGGER.error("Authentication failed for bill summary, returning empty data")
                return {}

        try:
            loop = asyncio.get_event_loop()
            _LOGGER.info("💳 Getting bill summary data...")

            # Get account information first
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)

            if not complete_data:
                _LOGGER.error("❌ No account data available for bill summary")
                return {}

            # Extract required IDs
            customer_id = complete_data.customer_id
            account_id = complete_data.account_ids[0] if complete_data.account_ids else None

            if not customer_id:
                _LOGGER.error("❌ No customer ID found for bill summary")
                return {}

            if not account_id:
                _LOGGER.error("❌ No account ID found for bill summary")
                return {}

            # Get bill summary using pymercury internal API client
            _LOGGER.info("📄 Requesting bill summary for account: %s", account_id)

            # Try using internal API client to get bill summary
            try:
                # Use internal _api_client if available
                if hasattr(self._client, '_api_client') and self._client._api_client:
                    _LOGGER.debug("🔧 Using _api_client for bill summary")
                    _LOGGER.debug("🔍 Checking get_bill_summary method signature...")

                    # Check method signature
                    import inspect
                    if hasattr(self._client._api_client, 'get_bill_summary'):
                        method_sig = inspect.signature(self._client._api_client.get_bill_summary)
                        _LOGGER.debug("📋 Method signature: %s", method_sig)

                        # Try different ways to call the method
                        if len(method_sig.parameters) == 0:
                            # No parameters - call without account_id
                            _LOGGER.error("🔧 Calling get_bill_summary() without parameters")
                            bill_summary = await loop.run_in_executor(
                                None,
                                lambda: self._client._api_client.get_bill_summary()
                            )
                        elif 'account_id' in method_sig.parameters:
                            # Has account_id parameter - try with both customer_id and account_id
                            if 'customer_id' in method_sig.parameters:
                                _LOGGER.error("🔧 Calling get_bill_summary(customer_id='%s', account_id='%s')", customer_id, account_id)
                                bill_summary = await loop.run_in_executor(
                                    None,
                                    lambda: self._client._api_client.get_bill_summary(customer_id=customer_id, account_id=account_id)
                                )
                            else:
                                _LOGGER.error("🔧 Calling get_bill_summary(account_id='%s')", account_id)
                                bill_summary = await loop.run_in_executor(
                                    None,
                                    lambda: self._client._api_client.get_bill_summary(account_id=account_id)
                                )
                        else:
                            # Try positional arguments with both customer_id and account_id
                            _LOGGER.error("🔧 Calling get_bill_summary('%s', '%s') positionally", customer_id, account_id)
                            bill_summary = await loop.run_in_executor(
                                None,
                                lambda: self._client._api_client.get_bill_summary(customer_id, account_id)
                            )
                    else:
                        raise AttributeError("get_bill_summary method not found")

                elif hasattr(self._client, 'api') and self._client.api:
                    _LOGGER.error("🔧 Using api client for bill summary")
                    # Try through the api attribute with both parameters
                    bill_summary = await loop.run_in_executor(
                        None,
                        lambda: self._client.api.get_bill_summary(customer_id, account_id)
                    )
                else:
                    # Fallback: try direct method (if it exists)
                    _LOGGER.error("🔧 Using direct client method for bill summary")
                    bill_summary = await loop.run_in_executor(
                        None,
                        lambda: self._client.get_bill_summary(customer_id, account_id)
                    )
            except AttributeError as attr_err:
                _LOGGER.warning("⚠️ Bill summary method not available in pymercury: %s", attr_err)
                _LOGGER.info("💡 Implementing manual bill summary API call...")

                # Manual implementation using Mercury API directly
                bill_summary = await self._get_bill_summary_manual(account_id)
            except Exception as api_err:
                _LOGGER.error("❌ Error calling bill summary API: %s", api_err)
                raise api_err

            if not bill_summary:
                _LOGGER.warning("⚠️ No bill summary data returned")
                return {}

            _LOGGER.info("✅ Successfully retrieved bill summary")
            _LOGGER.debug("📋 Raw bill summary data: %s", bill_summary)
            _LOGGER.debug("📋 Bill summary type: %s", type(bill_summary))

            # Normalize the bill summary data
            normalized_bill = self._normalize_bill_data(bill_summary)
            _LOGGER.debug("Normalized bill data: %s", normalized_bill)
            return normalized_bill

        except Exception as exc:
            if ("Tokens expired" in str(exc) or "refresh failed" in str(exc)) and _retry_count == 0:
                _LOGGER.warning("🔄 Tokens expired during bill summary, attempting re-authentication...")
                self._authenticated = False
                success = await self.authenticate()
                if success:
                    _LOGGER.info("✅ Re-authentication successful, retrying bill summary...")
                    return await self.get_bill_summary(_retry_count + 1)
                else:
                    _LOGGER.error("❌ Re-authentication failed for bill summary")
                    return {}
            else:
                _LOGGER.error("❌ Error fetching bill summary data: %s", exc, exc_info=True)
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

            _LOGGER.debug("✅ Normalized bill data: %s", normalized)
            return normalized

        except Exception as exc:
            _LOGGER.error("❌ Error normalizing bill data: %s", exc)
            return {}

    async def _get_bill_summary_manual(self, account_id: str) -> dict[str, Any]:
        """Manually get bill summary using Mercury API endpoint."""
        try:
            # Get the authenticated API client
            if not hasattr(self._client, 'api') or not self._client.api:
                _LOGGER.error("❌ No authenticated API client available for manual bill call")
                return {}

            loop = asyncio.get_event_loop()

            # Try to call the bill summary endpoint directly
            # Mercury API likely has endpoints like /bill-summary or /billing
            _LOGGER.info("🔗 Attempting manual bill summary API call...")

            # Check if api client has a generic request method
            api_client = self._client.api
            if hasattr(api_client, 'get') or hasattr(api_client, 'request'):
                # Try different possible endpoints
                possible_endpoints = [
                    f"/accounts/{account_id}/bill-summary",
                    f"/accounts/{account_id}/billing",
                    f"/bill-summary/{account_id}",
                    f"/billing/{account_id}",
                    f"/accounts/{account_id}/statement"
                ]

                for endpoint in possible_endpoints:
                    try:
                        _LOGGER.debug(f"🔍 Trying endpoint: {endpoint}")

                        if hasattr(api_client, 'get'):
                            response = await loop.run_in_executor(None, api_client.get, endpoint)
                        elif hasattr(api_client, 'request'):
                            response = await loop.run_in_executor(None, api_client.request, 'GET', endpoint)
                        else:
                            continue

                        if response:
                            _LOGGER.info(f"✅ Found bill data at endpoint: {endpoint}")
                            return response

                    except Exception as endpoint_err:
                        _LOGGER.debug(f"❌ Endpoint {endpoint} failed: {endpoint_err}")
                        continue

            # If direct API calls don't work, try to extract from existing data
            _LOGGER.info("💡 Trying to extract billing data from complete account data...")
            complete_data = await loop.run_in_executor(None, self._client.get_complete_account_data)

            if complete_data:
                # Check if complete_data has any billing attributes
                billing_data = {}

                for attr_name in dir(complete_data):
                    if not attr_name.startswith('_'):
                        attr_value = getattr(complete_data, attr_name)

                        # Look for billing-related attributes
                        if any(keyword in attr_name.lower() for keyword in ['bill', 'balance', 'payment', 'due', 'invoice']):
                            billing_data[attr_name] = attr_value
                            _LOGGER.info(f"🎯 Found billing attribute: {attr_name} = {attr_value}")

                if billing_data:
                    _LOGGER.info("✅ Extracted billing data from complete account data")
                    return billing_data

            _LOGGER.warning("⚠️ No billing data found through manual methods")
            return {}

        except Exception as exc:
            _LOGGER.error("❌ Error in manual bill summary call: %s", exc, exc_info=True)
            return {}



    async def _execute_api_call_with_fallback(self, api_method, customer_id, account_id, service_id,
                                            usage_key, history_key, log_message, success_message, error_message):
        """DRY helper method to eliminate repeated API call patterns."""
        constants = APIConstants()
        loop = asyncio.get_event_loop()

        try:
            _LOGGER.info(log_message)
            result = await loop.run_in_executor(
                None,
                api_method,
                customer_id, account_id, service_id
            )

            if result:
                usage_value = round(result.total_usage, constants.DECIMAL_PLACES)
                history_data = getattr(result, 'daily_usage', constants.FALLBACK_EMPTY_LIST) or constants.FALLBACK_EMPTY_LIST

                # Special handling for monthly data
                if 'monthly' in history_key:
                    history_data = self._extract_monthly_usage_data(result)
                    if not history_data and hasattr(result, 'daily_usage') and result.daily_usage:
                        _LOGGER.warning(constants.MSG_ERROR_EXTRACTION, len(result.daily_usage))
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
                    usage_key: constants.FALLBACK_ZERO,
                    history_key: constants.FALLBACK_EMPTY_LIST
                }

        except Exception as e:
            _LOGGER.warning(error_message, e)
            return {
                usage_key: constants.FALLBACK_ZERO,
                history_key: constants.FALLBACK_EMPTY_LIST
            }

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
            _LOGGER.info("📊 Getting electricity usage data...")

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
                _LOGGER.error("❌ No electricity usage data returned")
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

            # Get hourly usage data using DRY helper method
            constants = APIConstants()
            hourly_result = await self._execute_api_call_with_fallback(
                self._client._api_client.get_electricity_usage_hourly,
                customer_id, account_id, service_id,
                "hourly_usage", "hourly_usage_history",
                constants.MSG_GETTING_HOURLY,
                constants.MSG_SUCCESS_HOURLY,
                constants.MSG_ERROR_HOURLY
            )
            normalized_data.update(hourly_result)

            # Get monthly usage data using DRY helper method
            monthly_result = await self._execute_api_call_with_fallback(
                self._client._api_client.get_electricity_usage_monthly,
                customer_id, account_id, service_id,
                "monthly_usage", "monthly_usage_history",
                constants.MSG_GETTING_MONTHLY,
                constants.MSG_SUCCESS_MONTHLY,
                constants.MSG_ERROR_MONTHLY
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
        constants = APIConstants()  # Define constants at method start for DRY principles

        try:
            # Basic usage statistics
            normalized_data["total_usage"] = round(usage.total_usage, constants.DECIMAL_PLACES)
            normalized_data["average_daily_usage"] = round(usage.average_daily_usage, constants.DECIMAL_PLACES)
            normalized_data["current_bill"] = round(usage.total_cost, constants.DECIMAL_PLACES)

            # Get latest day's data
            if usage.daily_usage:
                latest_day = usage.daily_usage[-1]
                normalized_data["latest_daily_usage"] = latest_day.get('consumption', constants.FALLBACK_ZERO)
                normalized_data["latest_daily_cost"] = latest_day.get('cost', constants.FALLBACK_ZERO)
            else:
                normalized_data["latest_daily_usage"] = constants.FALLBACK_ZERO
                normalized_data["latest_daily_cost"] = constants.FALLBACK_ZERO

            # Temperature data using constants
            if usage.average_temperature is not None:
                normalized_data["average_temperature"] = round(usage.average_temperature, constants.TEMP_DECIMAL_PLACES)
            else:
                normalized_data["average_temperature"] = constants.FALLBACK_ZERO

            # Current temperature (from latest temperature reading)
            if usage.temperature_data:
                latest_temp = usage.temperature_data[-1]
                normalized_data["current_temperature"] = latest_temp.get('temp', constants.FALLBACK_ZERO)
            else:
                normalized_data["current_temperature"] = constants.FALLBACK_ZERO

            # Store detailed data for graph cards using constants for fallbacks
            normalized_data["daily_usage_history"] = usage.daily_usage if usage.daily_usage else constants.FALLBACK_EMPTY_LIST
            normalized_data["temperature_history"] = usage.temperature_data if usage.temperature_data else constants.FALLBACK_EMPTY_LIST

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
                    normalized_data["average_daily_usage"] = round(average_daily_consumption, 2)
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
