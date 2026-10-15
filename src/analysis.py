import numpy as np
import pandas as pd

from src import config


def add_price_changes(prices: pd.DataFrame) -> pd.DataFrame:
    """pct_change: vs the previous update; pct_change_in_session: only when both updates share a session."""
    prices = prices.copy()
    # A change from a zero price is undefined; zero answers are reported separately.
    prices["pct_change"] = (prices["price"].pct_change(fill_method=None) * 100).replace([np.inf, -np.inf], np.nan)
    in_session = prices.groupby("session_id")["price"].pct_change(fill_method=None) * 100
    prices["pct_change_in_session"] = in_session.replace([np.inf, -np.inf], np.nan)
    return prices


def session_stats(prices: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """One row per session instance; volatility uses changes between updates inside the session."""
    grouped = prices.groupby("session_id")
    stats = grouped.agg(
        n_updates=("price", "size"),
        first_update_et=("updated_at_et", "first"),
        last_update_et=("updated_at_et", "last"),
        first_price=("price", "first"),
        last_price=("price", "last"),
        min_price=("price", "min"),
        max_price=("price", "max"),
        n_changes=("pct_change_in_session", "count"),
        mean_pct_change=("pct_change_in_session", "mean"),
        std_pct_change=("pct_change_in_session", "std"),
        min_pct_change=("pct_change_in_session", "min"),
        max_pct_change=("pct_change_in_session", "max"),
        mean_abs_pct_change=("pct_change_in_session", lambda s: s.abs().mean()),
    )
    out = calendar.drop(columns=["start_utc", "end_utc"]).merge(stats, on="session_id", how="left")
    out["n_updates"] = out["n_updates"].fillna(0).astype(int)
    out["n_changes"] = out["n_changes"].fillna(0).astype(int)
    out["session_return_pct"] = (out["last_price"] / out["first_price"] - 1) * 100
    return out


def session_type_summary(prices: pd.DataFrame, stats: pd.DataFrame) -> pd.DataFrame:
    """Pools all in-session price changes by session type."""
    changes = prices.dropna(subset=["pct_change_in_session"]).groupby("session_type")["pct_change_in_session"]
    pooled = changes.agg(
        n_changes="count",
        mean_pct_change="mean",
        std_pct_change="std",
        min_pct_change="min",
        max_pct_change="max",
    )
    pooled["mean_abs_pct_change"] = changes.apply(lambda s: s.abs().mean())
    per_session = stats.groupby("session_type").agg(
        n_sessions=("session_id", "size"),
        n_sessions_with_updates=("n_updates", lambda s: int((s > 0).sum())),
        n_updates=("n_updates", "sum"),
        avg_updates_per_session=("n_updates", "mean"),
        mean_session_std_pct_change=("std_pct_change", "mean"),
        median_session_std_pct_change=("std_pct_change", "median"),
    )
    order = config.OPEN_SESSIONS + config.CLOSED_SESSIONS
    out = per_session.join(pooled, how="left").reindex([s for s in order if s in per_session.index])
    return out.reset_index()


def _transition_category(from_type: str, to_type: str) -> str:
    if from_type in config.CLOSED_SESSIONS and to_type not in config.CLOSED_SESSIONS:
        return f"{from_type}_to_workday"
    if to_type in config.CLOSED_SESSIONS:
        return "closure_start"
    return "intraday"


def transitions(prices: pd.DataFrame, stats: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Price change across every session boundary: last update before vs first update after it.

    Weekend/holiday re-opens are categorised as weekend_to_workday / holiday_to_workday.
    """
    times = prices["updated_at_utc"]
    first_in_session = prices.groupby("session_id").head(1).set_index("session_id")
    n_updates = stats.set_index("session_id")["n_updates"]

    rows = []
    for prev, cur in zip(calendar.itertuples(), calendar.iloc[1:].itertuples()):
        boundary = cur.start_utc
        before_idx = times.searchsorted(boundary, side="left") - 1
        before = prices.iloc[before_idx] if before_idx >= 0 else None
        after = first_in_session.loc[cur.session_id] if cur.session_id in first_in_session.index else None
        category = _transition_category(prev.session_type, cur.session_type)
        row = {
            "transition_type": f"{prev.session_type}->{cur.session_type}",
            "category": category,
            "from_session_id": prev.session_id,
            "to_session_id": cur.session_id,
            "boundary_et": cur.start_et,
            "price_before": before["price"] if before is not None else np.nan,
            "price_before_et": before["updated_at_et"] if before is not None else None,
            "price_after": after["price"] if after is not None else np.nan,
            "price_after_et": after["updated_at_et"] if after is not None else None,
            "first_update_delay_min": (
                (after["updated_at_utc"] - boundary).total_seconds() / 60 if after is not None else np.nan
            ),
        }
        if prev.is_closed:
            row["closure_start_et"] = prev.start_et
            row["closure_hours"] = (prev.end_utc - prev.start_utc).total_seconds() / 3600
            row["updates_during_closure"] = int(n_updates.get(prev.session_id, 0))
        rows.append(row)

    out = pd.DataFrame(rows)
    out["pct_change"] = ((out["price_after"] / out["price_before"] - 1) * 100).replace([np.inf, -np.inf], np.nan)
    out["abs_pct_change"] = out["pct_change"].abs()
    out["updates_during_closure"] = out["updates_during_closure"].astype("Int64")
    return out


def zero_prices(prices: pd.DataFrame) -> pd.DataFrame:
    cols = ["updated_at_et", "session_type", "session_id", "trading_date", "round_id", "block_number", "tx_hash"]
    return prices.loc[prices["answer_raw"] == 0, cols].reset_index(drop=True)


def unchanged_runs(prices: pd.DataFrame) -> pd.DataFrame:
    """Runs of 2+ consecutive updates reporting the exact same answer."""
    run_id = (prices["answer_raw"] != prices["answer_raw"].shift()).cumsum()
    rows = []
    for _, run in prices.groupby(run_id):
        if len(run) < 2:
            continue
        sessions = run["session_id"].unique()
        rows.append(
            {
                "start_et": run["updated_at_et"].iloc[0],
                "end_et": run["updated_at_et"].iloc[-1],
                "n_updates": len(run),
                "duration_min": (run["updated_at_utc"].iloc[-1] - run["updated_at_utc"].iloc[0]).total_seconds() / 60,
                "price": run["price"].iloc[0],
                "is_zero": bool(run["answer_raw"].iloc[0] == 0),
                "session_types": "|".join(run["session_type"].unique()),
                "session_ids": "|".join(sessions),
                "crosses_session_boundary": len(sessions) > 1,
                "first_round_id": run["round_id"].iloc[0],
                "last_round_id": run["round_id"].iloc[-1],
            }
        )
    columns = ["start_et", "end_et", "n_updates", "duration_min", "price", "is_zero", "session_types", "session_ids",
               "crosses_session_boundary", "first_round_id", "last_round_id"]
    return pd.DataFrame(rows, columns=columns)
