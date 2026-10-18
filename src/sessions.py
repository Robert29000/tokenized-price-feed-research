from datetime import date, datetime, timedelta

import exchange_calendars as xcals
import pandas as pd

from src import config

UTC_DTYPE = "datetime64[ns, UTC]"


def _nyse_sessions(start: date, end: date) -> set[date]:
    cal = xcals.get_calendar("XNYS", start=pd.Timestamp(start), end=pd.Timestamp(end))
    return {ts.date() for ts in cal.sessions}


def _at(day: date, t) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day, t, tzinfo=config.ET))


def _closed_type(day: date) -> str:
    return "weekend" if day.weekday() >= 5 else "holiday"


def build_session_calendar(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Every session instance covering [start, end), clipped to the window.

    Overnight [20:00, 04:00) ET belongs to the next trading day. A trading day that is not an NYSE
    session is closed from 20:00 ET the day before to 20:00 ET that day; consecutive closed days are
    merged into one closure, typed "holiday" if it contains a weekday holiday, otherwise "weekend".
    """
    start_et, end_et = start.tz_convert(config.ET), end.tz_convert(config.ET)
    first_day = start_et.date()
    last_day = end_et.date() + timedelta(days=1)
    open_days = _nyse_sessions(first_day - timedelta(days=7), last_day + timedelta(days=7))

    rows = []
    day = first_day
    while day <= last_day:
        prev_evening = _at(day - timedelta(days=1), config.OVERNIGHT_START)
        if day in open_days:
            bounds = [
                ("overnight", prev_evening, _at(day, config.PRE_MARKET_START)),
                ("pre_market", _at(day, config.PRE_MARKET_START), _at(day, config.REGULAR_START)),
                ("regular", _at(day, config.REGULAR_START), _at(day, config.POST_MARKET_START)),
                ("post_market", _at(day, config.POST_MARKET_START), _at(day, config.OVERNIGHT_START)),
            ]
            rows += [{"session_type": s, "trading_date": day, "start": a, "end": b} for s, a, b in bounds]
        else:
            session_type = _closed_type(day)
            if rows and rows[-1]["session_type"] in config.CLOSED_SESSIONS:
                last = rows[-1]
                last["end"] = _at(day, config.OVERNIGHT_START)
                if session_type == "holiday":
                    last["session_type"] = "holiday"
            else:
                rows.append(
                    {"session_type": session_type, "trading_date": day, "start": prev_evening,
                     "end": _at(day, config.OVERNIGHT_START)}
                )
        day += timedelta(days=1)

    cal = pd.DataFrame(rows)
    cal = cal[(cal["end"] > start_et) & (cal["start"] < end_et)].copy()
    cal["start"] = cal["start"].clip(lower=start_et)
    cal["end"] = cal["end"].clip(upper=end_et)
    for col in ("start", "end"):
        cal[f"{col}_utc"] = cal[col].dt.tz_convert("UTC").astype(UTC_DTYPE)
        cal[f"{col}_et"] = cal[col].map(lambda t: t.isoformat())
    cal["session_id"] = cal["trading_date"].astype(str) + "_" + cal["session_type"]
    cal["is_closed"] = cal["session_type"].isin(config.CLOSED_SESSIONS)
    cols = ["session_id", "session_type", "trading_date", "is_closed", "start_et", "end_et", "start_utc", "end_utc"]
    return cal[cols].reset_index(drop=True)


def label_sessions(prices: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Attaches session_id, session_type and trading_date to each update via its updatedAt time."""
    labeled = pd.merge_asof(
        # Stable sort: rounds that share an updatedAt (same block) keep their round order.
        prices.sort_values("updated_at_utc", kind="stable"),
        calendar[["start_utc", "session_id", "session_type", "trading_date"]],
        left_on="updated_at_utc",
        right_on="start_utc",
        direction="backward",
    ).drop(columns="start_utc")
    labeled["updated_at_et"] = labeled["updated_at_utc"].dt.tz_convert(config.ET).map(lambda t: t.isoformat())
    return labeled
