from __future__ import annotations

import datetime
import re
from typing import Tuple

TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
WEEKDAY_NAMES_CN = ["一", "二", "三", "四", "五", "六", "日"]


def parse_time_str(time_str: str) -> datetime.time:
    """Parse a 24-hour time string in HH:MM format into datetime.time.

    Args:
        time_str: String formatted as HH:MM.

    Returns:
        datetime.time object.

    Raises:
        ValueError: If time_str does not match 24-hour HH:MM format.
    """
    time_str = time_str.strip()
    match = TIME_PATTERN.match(time_str)
    if not match:
        raise ValueError(
            f"Invalid 24-hour time format: '{time_str}'. Expected HH:MM between 00:00 and 23:59."
        )
    hour = int(match.group(1))
    minute = int(match.group(2))
    return datetime.time(hour=hour, minute=minute)


def time_to_minutes(t: datetime.time) -> int:
    """Convert a datetime.time object to minutes since 00:00."""
    return t.hour * 60 + t.minute


def is_time_in_range(
    target: datetime.time,
    start: datetime.time,
    end: datetime.time,
    inclusive_end: bool = False,
) -> bool:
    """Check if target time is within [start, end].

    Handles both normal ranges (start <= end) and cross-midnight ranges (start > end, e.g. 22:00 -> 06:00).

    Args:
        target: The time to test.
        start: Start time of interval.
        end: End time of interval.
        inclusive_end: If True, end time boundary is inclusive [start, end].
                       If False, end time is exclusive [start, end).

    Returns:
        True if target is within the range, False otherwise.
    """
    target_m = time_to_minutes(target)
    start_m = time_to_minutes(start)
    end_m = time_to_minutes(end)

    if start_m == end_m:
        # Full day or single instant
        return True

    if start_m < end_m:
        # Normal daytime interval, e.g. 08:30 -> 12:00
        if inclusive_end:
            return start_m <= target_m <= end_m
        return start_m <= target_m < end_m
    else:
        # Crosses midnight, e.g. 22:00 -> 06:00
        if inclusive_end:
            return target_m >= start_m or target_m <= end_m
        return target_m >= start_m or target_m < end_m


def seconds_until_next_run(
    target_time_str: str,
    now: datetime.datetime | None = None,
) -> float:
    """Calculate seconds until the next occurrence of a daily 24h HH:MM time.

    Args:
        target_time_str: Target time string in HH:MM format.
        now: Current datetime, defaults to datetime.datetime.now().

    Returns:
        Float number of seconds until the next occurrence.
    """
    if now is None:
        now = datetime.datetime.now()

    target_time = parse_time_str(target_time_str)
    target_dt = now.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=0,
        microsecond=0,
    )

    if target_dt <= now:
        # Has already passed today; schedule for tomorrow
        target_dt += datetime.timedelta(days=1)

    return max(0.0, (target_dt - now).total_seconds())


def get_today_str(dt: datetime.datetime | None = None) -> str:
    """Return date string in YYYY-MM-DD format."""
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%Y-%m-%d")


def get_weekday_cn(dt: datetime.datetime | None = None) -> str:
    """Return Chinese weekday name (一, 二, 三, 四, 五, 六, 日)."""
    if dt is None:
        dt = datetime.datetime.now()
    return WEEKDAY_NAMES_CN[dt.weekday()]


def get_current_time_str(dt: datetime.datetime | None = None) -> str:
    """Return current time in HH:MM format."""
    if dt is None:
        dt = datetime.datetime.now()
    return dt.strftime("%H:%M")
