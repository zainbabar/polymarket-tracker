"""Data models for Polymarket tracker."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SignalType(str, Enum):
    LARGE_TRADE_BEFORE_RESOLUTION = "LARGE_TRADE_BEFORE_RESOLUTION"
    WALLET_CLUSTER = "WALLET_CLUSTER"
    VOLUME_ANOMALY = "VOLUME_ANOMALY"


class Market(BaseModel):
    """Polymarket market data."""

    condition_id: str
    question: str
    slug: str
    end_date: Optional[datetime] = None
    volume: float = 0.0
    volume_24h: float = 0.0
    liquidity: float = 0.0
    outcomes: list[str] = Field(default_factory=list)
    outcome_prices: list[float] = Field(default_factory=list)
    active: bool = True


class Trade(BaseModel):
    """Individual trade on Polymarket."""

    transaction_hash: str
    wallet: str
    market_id: str
    market_slug: str
    market_question: str
    side: Side
    outcome: str
    outcome_index: int
    size: float  # Number of shares
    price: float  # Price per share (0-1)
    usd_value: float  # Total USD value
    timestamp: datetime


class Alert(BaseModel):
    """Suspicious activity alert."""

    signal_type: SignalType
    severity: Severity
    market: Market
    description: str
    details: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trades: list[Trade] = Field(default_factory=list)
    wallets: list[str] = Field(default_factory=list)

    @property
    def score(self) -> float:
        """Numeric score for ranking alerts."""
        severity_scores = {
            Severity.LOW: 1.0,
            Severity.MEDIUM: 2.0,
            Severity.HIGH: 3.0,
            Severity.CRITICAL: 4.0,
        }
        return severity_scores.get(self.severity, 0.0)


class WalletCluster(BaseModel):
    """Group of wallets trading in coordinated patterns."""

    wallets: list[str]
    markets: list[str]  # Market IDs where coordination detected
    total_volume: float
    coordination_score: float  # 0-1 score of how coordinated
    first_seen: datetime
    last_seen: datetime


class VolumeStats(BaseModel):
    """Volume statistics for a market."""

    market_id: str
    current_volume: float
    mean_volume: float
    std_volume: float
    z_score: float
    period_start: datetime
    period_end: datetime
