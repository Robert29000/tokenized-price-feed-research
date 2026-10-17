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

## Notebook

`research.ipynb` examines each feed in a separate section. It reads the logs in `data/`, so run `main.py` first. For each feed, the notebook shows these items:

- For each session type, one plot of the prices and one plot of the absolute price changes.
- The mean, the standard deviation, the minimum and the maximum of the absolute price change for each session type.
- The same statistics for each transition type, and a list of all weekend closures and holiday closures.
- The zero answers and the unchanged runs, for each session type and for each session.

```bash
.venv/bin/pip install jupyterlab
.venv/bin/jupyter lab research.ipynb   # start Jupyter from the repository root
```

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
| `transitions.csv` | One row for each session boundary in a trading day, and one row for each closure. `price_before` is the last update before the boundary. `price_after` is the first update in the next session. The row also gives `pct_change` and the time from the boundary to the first update. `transition_type` and `category` identify the boundary (see [Transition types](#transition-types)). A closure row also gives the closure start, the closure length and `updates_during_closure`. |
| `zero_prices.csv` | Updates with `answer == 0`, and their session. |
| `unchanged_runs.csv` | Sequences of 2 or more consecutive updates with the same answer. Columns: start, end, number of updates, sessions, and a flag that shows if the sequence crosses a session boundary. |

## Transition types

`transition_type` is `<previous session>-><next session>`. There are 6 types in 2 categories.

| `transition_type` | Boundary (ET) | `category` |
|---|---|---|
| `overnight->pre_market` | 04:00 | `intraday` |
| `pre_market->regular` | 09:30, regular open | `intraday` |
| `regular->post_market` | 16:00, regular close | `intraday` |
| `post_market->overnight` | 20:00, if the next day is a trading day (Monday to Thursday) | `intraday` |
| `post_market->overnight (weekend)` | Friday 20:00 to Sunday 20:00 | `closure` |
| `post_market->overnight (holiday)` | 20:00 on the last trading day before a holiday to 20:00 on the last closed day | `closure` |

A closure goes from 20:00 to 20:00. Thus the session before a closure is always `post_market`, and the session after a closure is always `overnight`. The script merges consecutive closed days into one closure. Thus a long weekend with a holiday gives 1 `holiday` row.

A closure gives 1 row. The feeds send almost no updates during a closure. Thus a separate row for the start of a closure has no price change. For a closure row, these rules apply:

- `price_before` is the last update before the closure starts.
- `price_after` is the first update in `overnight` after the closure. The row does not use the first update of the `regular` session on the next morning.
- The calculation does not use the updates inside the closure. `updates_during_closure` gives the number of these updates.
- `boundary_et` is the end of the closure. `first_update_delay_min` starts at this time.

The time window clips the first session and the last session. The first session has no transition into it, and the last session has no transition out of it. A closure that the time window clips gives no row.

## Files

```
main.py            CLI: fetch logs, decode, label sessions, analyse, write CSV files
src/config.py      environment variables, feed addresses, session boundaries
src/etherscan.py   Etherscan client: request interval, retries with backoff, block-range split at the 1000-log limit
src/events.py      AnswerUpdated ABI, topic0, log decoding
src/sessions.py    session calendar and session labels
src/analysis.py    statistics
research.ipynb     notebook: plots and statistics for each feed
```
