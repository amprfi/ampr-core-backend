"""
Global notification rate limit configuration.

Defines the maximum number of notifications that can be sent to a user
within a rolling time window, broken down by priority level and per-module.

These are system-wide defaults applied equally to all users.
Adjust the constants below to tune notification frequency.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PriorityRateLimit:
    """Rate limit for a single priority tier."""
    max_per_window: int
    window_hours: int


@dataclass(frozen=True)
class RateLimitConfig:
    """Complete rate limit configuration."""
    high: PriorityRateLimit
    medium: PriorityRateLimit
    low: PriorityRateLimit
    # Maximum notifications from a single module per day
    max_per_module_per_day: int


# ============================================================================
# DEFAULTS — adjust these values as needed
# ============================================================================

DEFAULT_RATE_LIMITS = RateLimitConfig(
    high=PriorityRateLimit(max_per_window=10, window_hours=24),
    medium=PriorityRateLimit(max_per_window=8, window_hours=24),
    low=PriorityRateLimit(max_per_window=2, window_hours=24),
    max_per_module_per_day=12,
)


def get_rate_limit_for_priority(priority: str) -> PriorityRateLimit:
    """Get the rate limit config for a priority level."""
    return getattr(DEFAULT_RATE_LIMITS, priority, DEFAULT_RATE_LIMITS.medium)
