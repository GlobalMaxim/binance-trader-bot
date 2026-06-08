import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    binance_api_key: str
    binance_secret: str
    postgres_dsn: str
    symbols: list[str]
    timeframe: str
    fetch_limit: int
    poll_interval: int


def load_config() -> Config:
    user = os.environ.get("POSTGRES_USER", "trader")
    password = os.environ.get("POSTGRES_PASSWORD", "trader")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "trader")

    return Config(
        binance_api_key=os.environ["BINANCE_API_KEY"],
        binance_secret=os.environ["BINANCE_SECRET_KEY"],
        postgres_dsn=f"postgresql://{user}:{password}@{host}:{port}/{db}",
        symbols=os.environ.get("SYMBOLS", "BTC/USDT,ETH/USDT").split(","),
        timeframe=os.environ.get("TIMEFRAME", "1m"),
        fetch_limit=int(os.environ.get("FETCH_LIMIT", "100")),
        poll_interval=int(os.environ.get("POLL_INTERVAL", "60")),
    )
