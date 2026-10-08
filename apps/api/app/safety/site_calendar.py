"""The Baytown site calendar, which decides "today" and the current reporting year.

Safety records are dated on the plant floor, so a record made this evening in
Baytown is dated today even after UTC midnight, and a new reporting year starts
at midnight America/Chicago on 1 January. Audit timestamps stay UTC; this is
only for calendar dates. The platform has one site; move this into site
configuration if it becomes multi-site.
"""

import datetime as dt
from zoneinfo import ZoneInfo

SITE_TIME_ZONE = ZoneInfo("America/Chicago")


def site_today(now: dt.datetime) -> dt.date:
    """The Baytown site's calendar date at the instant ``now`` (timezone-aware)."""
    return now.astimezone(SITE_TIME_ZONE).date()
