import logging
import threading
import time

import requests

from src import config

log = logging.getLogger(__name__)

# getLogs returns at most 1000 records per call; a full response may be truncated.
LOG_LIMIT = 1000
# Initial chunk size (~7 days of mainnet blocks) so most requests stay well below LOG_LIMIT.
MAX_BLOCK_RANGE = 50_000

RATE_LIMIT_TERMS = ("rate limit", "max calls per sec", "too many requests")
RANGE_LIMIT_TERMS = ("result window is too large", "too many", "query timeout", "timeout")


class EtherscanError(Exception):
    pass


def hex_to_int(value: str) -> int:
    """Etherscan returns hex numbers and sometimes "0x" for zero."""
    return int(value, 16) if value not in ("", "0x") else 0


class RequestPacer:
    """Enforces a minimum interval between consecutive requests."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class EtherscanClient:
    def __init__(
        self,
        api_key: str = config.ETHERSCAN_API_KEY,
        chain_id: int = config.CHAIN_ID,
        min_interval: float = config.ETHERSCAN_MIN_INTERVAL,
        retries: int = 5,
        timeout: float = 30,
    ):
        if not api_key:
            raise EtherscanError("ETHERSCAN_API_KEY is not set (see .env.example)")
        self.api_key = api_key
        self.chain_id = chain_id
        self.retries = retries
        self.timeout = timeout
        self.pacer = RequestPacer(min_interval)
        self.session = requests.Session()

    def _query(self, params: dict) -> dict:
        """Sends one request with pacing and retries.

        Returns the parsed body. Range-limit errors are returned (not raised) so the caller can split the range.
        """
        params = {"chainid": self.chain_id, "apikey": self.api_key, **params}
        last_error = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(min(0.5 * 2**attempt, 8))
            self.pacer.wait()
            try:
                resp = self.session.get(config.ETHERSCAN_API_URL, params=params, timeout=self.timeout)
                body = resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Etherscan request failed (attempt %d): %s", attempt + 1, last_error)
                continue

            # Proxy (JSON-RPC) responses have no "status" field.
            if "status" not in body:
                if "error" in body:
                    last_error = str(body["error"])
                    continue
                return body

            if body["status"] == "1":
                return body

            message = str(body.get("message", ""))
            result = body.get("result")
            text = f"{message} {result if isinstance(result, str) else ''}".lower()
            if "no records found" in text:
                return {**body, "result": []}
            if any(term in text for term in RATE_LIMIT_TERMS) and "daily" not in text:
                last_error = text
                log.info("Rate limited, backing off (attempt %d)", attempt + 1)
                continue
            if any(term in text for term in RANGE_LIMIT_TERMS):
                return body
            raise EtherscanError(f"Etherscan error: {message}: {result}")
        raise EtherscanError(f"Etherscan request failed after {self.retries + 1} attempts: {last_error}")

    def get_block_by_time(self, timestamp: int, closest: str = "before") -> int:
        body = self._query(
            {"module": "block", "action": "getblocknobytime", "timestamp": int(timestamp), "closest": closest}
        )
        return int(body["result"])

    def eth_call(self, to: str, data: str) -> str:
        body = self._query({"module": "proxy", "action": "eth_call", "to": to, "data": data, "tag": "latest"})
        return body["result"]

    def get_logs(self, address: str, topic0: str, from_block: int, to_block: int) -> list[dict]:
        logs: dict[tuple[str, str], dict] = {}
        for start in range(from_block, to_block + 1, MAX_BLOCK_RANGE):
            end = min(start + MAX_BLOCK_RANGE - 1, to_block)
            for entry in self._logs_range(address, topic0, start, end):
                logs[(entry["transactionHash"], entry["logIndex"])] = entry
        return sorted(logs.values(), key=lambda e: (hex_to_int(e["blockNumber"]), hex_to_int(e["logIndex"])))

    def _logs_range(self, address: str, topic0: str, from_block: int, to_block: int) -> list[dict]:
        body = self._query(
            {
                "module": "logs",
                "action": "getLogs",
                "address": address,
                "topic0": topic0,
                "fromBlock": from_block,
                "toBlock": to_block,
                "page": 1,
                "offset": LOG_LIMIT,
            }
        )
        result = body.get("result")
        limited = not isinstance(result, list) or len(result) >= LOG_LIMIT
        if not limited:
            log.debug("getLogs %s [%d, %d]: %d logs", address, from_block, to_block, len(result))
            return result

        if from_block >= to_block:
            raise EtherscanError(f"block {from_block} alone reaches the getLogs {LOG_LIMIT}-record cap")
        mid = (from_block + to_block) // 2
        log.info("getLogs %s [%d, %d] hit the limit, splitting at %d", address, from_block, to_block, mid)
        return self._logs_range(address, topic0, from_block, mid) + self._logs_range(address, topic0, mid + 1, to_block)
