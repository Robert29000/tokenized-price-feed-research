# Tokenized price feeds research

This project analyses Chainlink 24/5 tokenized-equity price feeds (NVDA, GOOGL, TSLA, SPCX) on Ethereum mainnet. It reads the `AnswerUpdated(int256 indexed current, uint256 indexed roundId, uint256 updatedAt)` event logs from the Etherscan v2 `getLogs` endpoint. It filters the logs by feed address and `topic0`. It labels each price update with its trading session in US Eastern Time. Then it writes statistics for each feed to CSV files.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then set ETHERSCAN_API_KEY
```

| Variable | Default | Meaning |
|---|---|---|
| `ETHERSCAN_API_KEY` | (required) | Etherscan API key |
| `CHAIN_ID` | `1` | Chain ID for the Etherscan v2 API |
| `ETHERSCAN_MIN_INTERVAL` | `0.35` | Minimum time in seconds between two requests. The free plan allows 3 calls per second and 100,000 calls per day. |

## Run

```bash
.venv/bin/python main.py                      # all feeds, last 2 months
.venv/bin/python main.py --feeds NVDA,TSLA --months 3
.venv/bin/python main.py --no-fetch           # analyse the logs in data/ again, without Etherscan requests
```

The script keeps the decoded logs in `data/<SYMBOL>.csv`. It keeps the time window, the block window and the feed decimals in `data/<SYMBOL>.meta.json`. It writes the results to `output/<SYMBOL>/`.

## Sessions

The session times come from the [Chainlink documentation](https://docs.chain.link/data-feeds/tokenized-equity-feeds#session-coverage). The script uses the `America/New_York` time zone. This time zone applies the daylight saving time changes.

| Session | Time window (ET) |
|---|---|
| `overnight` | 20:00 – 04:00. This session belongs to the next trading day. |
| `pre_market` | 04:00 – 09:30 |
| `regular` | 09:30 – 16:00 |
| `post_market` | 16:00 – 20:00 |
| `weekend` | Friday 20:00 – Sunday 20:00 |
| `holiday` | 20:00 on the day before an NYSE holiday – 20:00 on the holiday |

The `exchange_calendars` XNYS calendar supplies the NYSE holidays. The script merges consecutive closed days into one closure. If the closure contains a weekday holiday, its type is `holiday`. Example: Labor Day 2026 gives one `holiday` closure from Friday 20:00 to Monday 20:00.

The calendar does not include early closes (half days).

## Output files (`output/<SYMBOL>/`)

| File | Content |
|---|---|
| `prices.csv` | One row for each price update. Columns: ET time, trading date, session, price, `pct_change` and `pct_change_in_session`. `pct_change` compares the price with the previous update. `pct_change_in_session` does the same, but only if the previous update is in the same session. |
| `session_stats.csv` | One row for each session, also for sessions without updates. Columns: number of updates, first, last, minimum and maximum price, and session return. Also the mean, standard deviation (sample), minimum, maximum and mean absolute value of the percent changes in the session. |
| `session_type_summary.csv` | The same values for all sessions of one type together. Also the mean and the median of the standard deviations of the sessions. |
| `transitions.csv` | One row for each session boundary. `price_before` is the last update before the boundary. `price_after` is the first update in the next session. The row also gives `pct_change` and the delay until the first update. `category` is `intraday`, `closure_start`, `weekend_to_workday` or `holiday_to_workday`. A reopen row also gives the closure start, the closure length and `updates_during_closure`. |
| `zero_prices.csv` | Updates with `answer == 0`, and their session. |
| `unchanged_runs.csv` | Sequences of 2 or more consecutive updates with the same answer. Columns: start, end, number of updates, sessions, and a flag that shows if the sequence crosses a session boundary. |

## Files

```
main.py            CLI: fetch logs, decode, label sessions, analyse, write CSV files
src/config.py      environment variables, feed addresses, session boundaries
src/etherscan.py   Etherscan client: request interval, retries with backoff, block-range split at the 1000-log limit
src/events.py      AnswerUpdated ABI, topic0, log decoding
src/sessions.py    session calendar and session labels
src/analysis.py    statistics
```
