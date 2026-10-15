import pandas as pd
from eth_abi import decode
from eth_utils import event_abi_to_log_topic, function_signature_to_4byte_selector

from src.etherscan import hex_to_int

# event AnswerUpdated(int256 indexed current, uint256 indexed roundId, uint256 updatedAt)
ANSWER_UPDATED_ABI = {
    "type": "event",
    "name": "AnswerUpdated",
    "anonymous": False,
    "inputs": [
        {"name": "current", "type": "int256", "indexed": True},
        {"name": "roundId", "type": "uint256", "indexed": True},
        {"name": "updatedAt", "type": "uint256", "indexed": False},
    ],
}
TOPIC0 = "0x" + event_abi_to_log_topic(ANSWER_UPDATED_ABI).hex()
DECIMALS_SELECTOR = "0x" + function_signature_to_4byte_selector("decimals()").hex()

COLUMNS = ["block_number", "block_ts", "tx_hash", "log_index", "round_id", "answer_raw", "updated_at"]


def _topic_bytes(topic: str) -> bytes:
    return bytes.fromhex(topic.removeprefix("0x"))


def decode_logs(raw_logs: list[dict]) -> pd.DataFrame:
    rows = []
    for entry in raw_logs:
        topics = entry["topics"]
        (current,) = decode(["int256"], _topic_bytes(topics[1]))
        (round_id,) = decode(["uint256"], _topic_bytes(topics[2]))
        (updated_at,) = decode(["uint256"], _topic_bytes(entry["data"]))
        rows.append(
            {
                "block_number": hex_to_int(entry["blockNumber"]),
                "block_ts": hex_to_int(entry["timeStamp"]),
                "tx_hash": entry["transactionHash"],
                "log_index": hex_to_int(entry["logIndex"]),
                "round_id": round_id,
                "answer_raw": current,
                "updated_at": updated_at,
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def to_prices(df: pd.DataFrame, decimals: int) -> pd.DataFrame:
    """Adds human-readable price and UTC timestamp columns, sorted by time."""
    df = df.copy()
    df["price"] = df["answer_raw"].astype(float) / 10**decimals
    df["updated_at_utc"] = pd.to_datetime(df["updated_at"], unit="s", utc=True).astype("datetime64[ns, UTC]")
    return df.sort_values(["updated_at", "round_id"]).reset_index(drop=True)
