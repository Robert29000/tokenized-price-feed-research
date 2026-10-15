import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from src import analysis, config, events, sessions
from src.etherscan import EtherscanClient, hex_to_int

log = logging.getLogger("feeds")


def fetch_feed(client: EtherscanClient, symbol: str, address: str, start_block: int, end_block: int) -> pd.DataFrame:
    raw = client.get_logs(address, events.TOPIC0, start_block, end_block)
    log.info("%s: fetched %d AnswerUpdated logs", symbol, len(raw))
    return events.decode_logs(raw)


def load_or_fetch(args, symbols: list[str]) -> dict[str, tuple[pd.DataFrame, dict]]:
    """Returns {symbol: (decoded logs, meta)}; meta holds the window and decimals. Caches to data/."""
    config.DATA_DIR.mkdir(exist_ok=True)
    result = {}
    client = None
    window = None
    for symbol in symbols:
        data_path = config.DATA_DIR / f"{symbol}.csv"
        meta_path = config.DATA_DIR / f"{symbol}.meta.json"
        if args.no_fetch:
            result[symbol] = (pd.read_csv(data_path), json.loads(meta_path.read_text()))
            continue

        if client is None:
            client = EtherscanClient()
            end = pd.Timestamp.now(tz="UTC").floor("s") - pd.Timedelta(minutes=1)
            start = end - pd.DateOffset(months=args.months)
            start_block = client.get_block_by_time(int(start.timestamp()), "after")
            end_block = client.get_block_by_time(int(end.timestamp()), "before")
            window = {"start": start.isoformat(), "end": end.isoformat(),
                      "start_block": start_block, "end_block": end_block}
            log.info("Window %s .. %s (blocks %d..%d)", start, end, start_block, end_block)

        address = config.FEEDS[symbol]
        decimals = hex_to_int(client.eth_call(address, events.DECIMALS_SELECTOR))
        df = fetch_feed(client, symbol, address, window["start_block"], window["end_block"])
        meta = {**window, "symbol": symbol, "address": address, "decimals": decimals}
        df.to_csv(data_path, index=False)
        meta_path.write_text(json.dumps(meta, indent=2))
        result[symbol] = (df, meta)
    return result


def analyze_feed(symbol: str, raw: pd.DataFrame, meta: dict, out_root) -> None:
    calendar = sessions.build_session_calendar(pd.Timestamp(meta["start"]), pd.Timestamp(meta["end"]))
    prices = events.to_prices(raw, meta["decimals"])
    prices = sessions.label_sessions(prices, calendar)
    prices = analysis.add_price_changes(prices)

    stats = analysis.session_stats(prices, calendar)
    outputs = {
        "prices": prices[["updated_at_et", "trading_date", "session_type", "session_id", "price", "pct_change",
                          "pct_change_in_session", "answer_raw", "round_id", "updated_at", "block_number",
                          "block_ts", "tx_hash", "log_index"]],
        "session_stats": stats,
        "session_type_summary": analysis.session_type_summary(prices, stats),
        "transitions": analysis.transitions(prices, stats, calendar),
        "zero_prices": analysis.zero_prices(prices),
        "unchanged_runs": analysis.unchanged_runs(prices),
    }
    out_dir = out_root / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in outputs.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    log.info(
        "%s: %d updates, %d sessions, %d zero prices, %d unchanged runs -> %s",
        symbol, len(prices), len(stats), len(outputs["zero_prices"]), len(outputs["unchanged_runs"]), out_dir,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Session analysis of Chainlink tokenized-equity price feeds")
    parser.add_argument("--months", type=int, default=2, help="lookback window in months (default 2)")
    parser.add_argument("--feeds", default=",".join(config.FEEDS), help="comma-separated symbols")
    parser.add_argument("--no-fetch", action="store_true", help="reuse cached logs from data/")
    parser.add_argument("--out", default=str(config.OUTPUT_DIR), help="output directory")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    symbols = [s.strip().upper() for s in args.feeds.split(",") if s.strip()]
    unknown = set(symbols) - set(config.FEEDS)
    if unknown:
        parser.error(f"unknown feeds: {', '.join(sorted(unknown))}")

    out_root = Path(args.out)
    for symbol, (raw, meta) in load_or_fetch(args, symbols).items():
        analyze_feed(symbol, raw, meta, out_root)


if __name__ == "__main__":
    main()
