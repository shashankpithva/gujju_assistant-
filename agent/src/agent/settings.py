"""Settings the agent and the dialer share, read from agent/.env."""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

TIME_FORMAT = "%Y-%m-%d %H:%M"  # the sheet's Last call column


def agent_name() -> str:
    """The name the dialer sends calls to: the agent and the dialer must use the same one."""
    return os.getenv("AGENT_NAME") or "gujju-survey"


def seconds(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


def survey_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("SURVEY_TIMEZONE") or "Asia/Kolkata")


def now() -> datetime:
    return datetime.now(survey_timezone())


def stamp(at: datetime | None = None) -> str:
    """A time as the sheet shows it, in the survey's timezone."""
    return (at or now()).astimezone(survey_timezone()).strftime(TIME_FORMAT)


def parse_stamp(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), TIME_FORMAT).replace(tzinfo=survey_timezone())
    except ValueError:
        return None
