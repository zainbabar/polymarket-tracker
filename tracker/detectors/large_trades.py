"""Detector for unusually large trades before market resolution."""

from datetime import datetime, timedelta
from typing import Optional
import statistics

from ..models import Alert, Market, Trade, Severity, SignalType
from ..api.gamma import GammaClient
from ..api.data import DataClient


class LargeTradeDetector:
    """Detects unusually large trades placed shortly before market resolution."""

    def __init__(
        self,
        gamma_client: GammaClient,
        data_client: DataClient,
        size_percentile: float = 95.0,
        time_window_hours: int = 24,
        min_trade_usd: float = 1000,
        high_confidence_threshold: float = 0.85,
    ):
        """Initialize the detector.

        Args:
            gamma_client: Client for market data
            data_client: Client for trade data
            size_percentile: Flag trades above this percentile
            time_window_hours: Hours before resolution to monitor
            min_trade_usd: Minimum trade size to consider
            high_confidence_threshold: Price threshold for "confident" bets
        """
        self.gamma = gamma_client
        self.data = data_client
        self.size_percentile = size_percentile
        self.time_window_hours = time_window_hours
        self.min_trade_usd = min_trade_usd
        self.high_confidence_threshold = high_confidence_threshold

    def scan(self, markets: Optional[list[Market]] = None) -> list[Alert]:
        """Scan markets for suspicious large trades.

        Args:
            markets: Markets to scan (defaults to markets closing soon)

        Returns:
            List of alerts for suspicious activity
        """
        if markets is None:
            markets = self.gamma.get_markets_closing_soon(
                hours=self.time_window_hours
            )

        alerts = []
        for market in markets:
            market_alerts = self.analyze_market(market)
            alerts.extend(market_alerts)

        return sorted(alerts, key=lambda a: a.score, reverse=True)

    def analyze_market(self, market: Market) -> list[Alert]:
        """Analyze a single market for suspicious large trades.

        Args:
            market: Market to analyze

        Returns:
            List of alerts
        """
        trades = self.data.get_trades(
            market=market.condition_id, limit=2000
        )

        if len(trades) < 10:
            return []

        trade_sizes = [t.usd_value for t in trades]
        threshold = self._calculate_percentile(trade_sizes, self.size_percentile)

        now = datetime.utcnow()
        window_start = now - timedelta(hours=self.time_window_hours)

        alerts = []
        for trade in trades:
            if trade.timestamp < window_start:
                continue

            if trade.usd_value < max(threshold, self.min_trade_usd):
                continue

            percentile = self._get_percentile_rank(trade_sizes, trade.usd_value)
            severity = self._calculate_severity(
                trade, market, percentile
            )

            time_to_resolution = None
            if market.end_date:
                time_to_resolution = market.end_date - trade.timestamp

            alert = Alert(
                signal_type=SignalType.LARGE_TRADE_BEFORE_RESOLUTION,
                severity=severity,
                market=market,
                description=f"Large ${trade.usd_value:,.0f} trade on {trade.outcome} at {trade.price:.2%}",
                details={
                    "trade_usd": trade.usd_value,
                    "trade_size": trade.size,
                    "price": trade.price,
                    "outcome": trade.outcome,
                    "percentile": percentile,
                    "time_to_resolution_hours": (
                        time_to_resolution.total_seconds() / 3600
                        if time_to_resolution
                        else None
                    ),
                    "wallet": trade.wallet,
                    "tx_hash": trade.transaction_hash,
                },
                trades=[trade],
                wallets=[trade.wallet],
                timestamp=trade.timestamp,
            )
            alerts.append(alert)

        return alerts

    def _calculate_severity(
        self, trade: Trade, market: Market, percentile: float
    ) -> Severity:
        """Calculate alert severity based on trade characteristics."""
        score = 0

        # Size factor
        if percentile >= 99:
            score += 3
        elif percentile >= 97:
            score += 2
        elif percentile >= 95:
            score += 1

        # Confidence factor (betting at extreme prices)
        if trade.price >= self.high_confidence_threshold:
            score += 2
        elif trade.price >= 0.75:
            score += 1

        # Time to resolution factor
        if market.end_date:
            hours_to_resolution = (
                market.end_date - trade.timestamp
            ).total_seconds() / 3600
            if hours_to_resolution <= 2:
                score += 3
            elif hours_to_resolution <= 6:
                score += 2
            elif hours_to_resolution <= 12:
                score += 1

        # USD value factor
        if trade.usd_value >= 50000:
            score += 2
        elif trade.usd_value >= 10000:
            score += 1

        if score >= 7:
            return Severity.CRITICAL
        elif score >= 5:
            return Severity.HIGH
        elif score >= 3:
            return Severity.MEDIUM
        return Severity.LOW

    def _calculate_percentile(self, values: list[float], percentile: float) -> float:
        """Calculate the value at a given percentile."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile / 100)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def _get_percentile_rank(self, values: list[float], value: float) -> float:
        """Get the percentile rank of a value in a distribution."""
        if not values:
            return 0.0
        count_below = sum(1 for v in values if v < value)
        return (count_below / len(values)) * 100
