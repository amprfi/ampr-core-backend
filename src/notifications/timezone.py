"""
Timezone utilities for notification delivery windows.

Provides country-to-UTC-offset mapping and delivery window calculations.
"""
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-3 country codes → UTC offset in hours
# Using primary timezone for each country (most populous region)
COUNTRY_UTC_OFFSET: dict[str, float] = {
    "USA": -5,    # Eastern Time
    "GBR": 0,     # GMT
    "CAN": -5,    # Eastern Time
    "AUS": 10,    # Sydney
    "DEU": 1,     # CET
    "FRA": 1,     # CET
    "JPN": 9,
    "CHN": 8,
    "IND": 5.5,
    "BRA": -3,
    "MEX": -6,    # Central Time
    "ESP": 1,     # CET
    "ITA": 1,     # CET
    "NLD": 1,     # CET
    "CHE": 1,     # CET
    "SGP": 8,
    "HKG": 8,
    "KOR": 9,
    "ARE": 4,
    "ZAF": 2,
    "NZL": 12,
    "IRL": 0,
    "SWE": 1,
    "NOR": 1,
    "DNK": 1,
    "FIN": 2,
    "POL": 1,
    "AUT": 1,
    "BEL": 1,
    "PRT": 0,
    "ISR": 2,
    "THA": 7,
    "MYS": 8,
    "PHL": 8,
    "IDN": 7,
    "VNM": 7,
    "ARG": -3,
    "CHL": -4,
    "COL": -5,
    "PER": -5,
    "NGA": 1,
    "EGY": 2,
    "KEN": 3,
    "RUS": 3,     # Moscow
    "TUR": 3,
    "SAU": 3,
    "PAK": 5,
    "BGD": 6,
    "TWN": 8,
    "UKR": 2,
    "GRC": 2,
    "CZE": 1,
    "ROU": 2,
    "HUN": 1,
}

DEFAULT_UTC_OFFSET = 0
DEFAULT_DELIVERY_WINDOW_START = 8   # 8:00 AM local
DEFAULT_DELIVERY_WINDOW_END = 20    # 8:00 PM local


class TimezoneUtils:
    """Utilities for timezone handling and delivery window calculations."""
    
    def __init__(
        self,
        delivery_window_start: int = DEFAULT_DELIVERY_WINDOW_START,
        delivery_window_end: int = DEFAULT_DELIVERY_WINDOW_END,
    ):
        self.delivery_window_start = delivery_window_start
        self.delivery_window_end = delivery_window_end
    
    def get_utc_offset_for_country(self, country: Optional[str]) -> float:
        """
        Get UTC offset (in hours) for a country code.
        
        Args:
            country: ISO 3166-1 alpha-3 country code (e.g., "USA", "GBR")
            
        Returns:
            UTC offset in hours (e.g., -5 for Eastern US, 5.5 for India)
        """
        if not country:
            return DEFAULT_UTC_OFFSET
        
        offset = COUNTRY_UTC_OFFSET.get(country.upper())
        if offset is not None:
            return offset
        
        logger.warning(f"Unknown country code '{country}', using UTC")
        return DEFAULT_UTC_OFFSET
    
    def resolve_user_utc_offset(
        self,
        user_timezone: Optional[str],
        user_country: Optional[str],
    ) -> float:
        """
        Resolve user's UTC offset with fallback to country-based detection.
        
        Priority:
        1. User's explicit timezone offset (if set as numeric string like "+5.5" or "-5")
        2. Country-based offset mapping
        3. UTC fallback (0)
        
        Args:
            user_timezone: User's explicit timezone preference (numeric offset string)
            user_country: User's country code from profile
            
        Returns:
            UTC offset in hours
        """
        if user_timezone:
            try:
                return float(user_timezone)
            except ValueError:
                logger.warning(f"Invalid timezone offset '{user_timezone}', falling back to country")
        
        return self.get_utc_offset_for_country(user_country)
    
    def get_local_time(self, utc_offset: float) -> datetime:
        """
        Get current local time for a UTC offset.
        
        Args:
            utc_offset: Offset from UTC in hours
            
        Returns:
            Current datetime in the specified offset
        """
        tz = timezone(timedelta(hours=utc_offset))
        return datetime.now(tz)
    
    def is_within_delivery_window(self, utc_offset: float) -> bool:
        """
        Check if current time is within the delivery window for a UTC offset.
        
        Args:
            utc_offset: Offset from UTC in hours
            
        Returns:
            True if within delivery window (e.g., 8am-8pm local time)
        """
        local_time = self.get_local_time(utc_offset)
        current_hour = local_time.hour + local_time.minute / 60
        
        return self.delivery_window_start <= current_hour < self.delivery_window_end
    
    def get_next_delivery_window_start(self, utc_offset: float) -> datetime:
        """
        Calculate the next delivery window start time in UTC.
        
        Args:
            utc_offset: Offset from UTC in hours
            
        Returns:
            datetime (UTC) of when the next delivery window starts
        """
        tz = timezone(timedelta(hours=utc_offset))
        local_now = datetime.now(tz)
        current_hour = local_now.hour + local_now.minute / 60
        
        if self.delivery_window_start <= current_hour < self.delivery_window_end:
            return datetime.now(timezone.utc)
        
        if current_hour < self.delivery_window_start:
            # Later today
            next_window_local = local_now.replace(
                hour=self.delivery_window_start,
                minute=0,
                second=0,
                microsecond=0,
            )
        else:
            # Tomorrow morning
            next_day = local_now + timedelta(days=1)
            next_window_local = next_day.replace(
                hour=self.delivery_window_start,
                minute=0,
                second=0,
                microsecond=0,
            )
        
        return next_window_local.astimezone(timezone.utc)
    
    def get_delivery_window(
        self,
        user_timezone: Optional[str],
        user_country: Optional[str],
    ) -> Tuple[bool, Optional[int]]:
        """
        Determine if notification can be delivered now or when to schedule.
        
        Args:
            user_timezone: User's explicit timezone offset (numeric string)
            user_country: User's country code from profile
            
        Returns:
            Tuple of (can_deliver_now, scheduled_for_ms)
            - If can_deliver_now is True, scheduled_for_ms is None
            - If can_deliver_now is False, scheduled_for_ms is Unix timestamp (ms)
        """
        utc_offset = self.resolve_user_utc_offset(user_timezone, user_country)
        
        if self.is_within_delivery_window(utc_offset):
            return (True, None)
        
        next_window = self.get_next_delivery_window_start(utc_offset)
        scheduled_for_ms = int(next_window.timestamp() * 1000)
        return (False, scheduled_for_ms)


_timezone_utils_instance: Optional[TimezoneUtils] = None


def get_timezone_utils() -> TimezoneUtils:
    """Get the singleton TimezoneUtils instance."""
    global _timezone_utils_instance
    if _timezone_utils_instance is None:
        _timezone_utils_instance = TimezoneUtils()
    return _timezone_utils_instance
