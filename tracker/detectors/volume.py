"""Detector for volume anomalies in market trading."""

from datetime import datetime, timedelta
from typing import Optional
import statistics

from ..models import Alert, Market, Severity, SignalType, VolumeStats
from ..api.gamma import GammaClient
from ..api.data import DataClient


class VolumeAnomalyDetector:
    """Detects unusual volume spikes that deviate from normal patterns."""

    def __init__(
        self,
        gamma_client: GammaClient,
        data_client: DataClient,
        z_score_threshold: float = 3.0,
        lookback_days: int = 7,
        min_trades_for_baseline: int = 50,
    ):
        """Initialize the detector.

        Args:
            gamma_client: Client for market data
            data_client: Client for trade data
            z_score_threshold: Standard deviations above mean to flag
            lookback_days: Days of history for baseline calculation
            min_trades_for_baseline: Minimum trades needed for analysis
        """
        self.gamma = gamma_client
        self.data = data_client
        self.z_score_threshold = z_score_threshold
        self.lookback_days = lookback_days
        self.min_trades_for_baseline = min_trades_for_baseline

    def scan(self, markets: Optional[list[Market]] = None) -> list[Alert]:
        """Scan markets for volume anomalies.

        Args:
            markets: Markets to scan (defaults to high-volume markets)

        Returns:
            List of alerts for volume anomalies
        """
        if markets is None:
            markets = self.gamma.get_high_volume_markets(limit=50)

        alerts = []
        for market in markets:
            alert = self.analyze_market(market)
            if alert:
                alerts.append(alert)

        return sorted(alerts, key=lambda a: a.score, reverse=True)

    def analyze_market(self, market: Market) -> Optional[Alert]:
        """Analyze a single market for volume anomalies.

        Args:
            market: Market to analyze

        Returns:
            Alert if anomaly detected, None otherwise
        """
        trades = self.data.get_trades(market=market.condition_id, limit=5000)

        if len(trades) < self.min_trades_for_baseline:
            return None

        now = datetime.utcnow()
        lookback_start = now - timedelta(days=self.lookback_days)

        # Calculate hourly volumes
        hourly_volumes = self._calculate_hourly_volumes(trades, lookback_start)

        if len(hourly_volumes) < 24:
            return None

        # Get recent vs historical volumes
        recent_hours = 6
        recent_volume = sum(hourly_volumes[-recent_hours:]) if len(hourly_volumes) >= recent_hours else 0
        historical_volumes = hourly_volumes[:-recent_hours] if len(hourly_volumes) > recent_hours else hourly_volumes

        if not historical_volumes:
            return None

        mean_volume = statistics.mean(historical_volumes)
        std_volume = statistics.stdev(historical_volumes) if len(historical_volumes) > 1 else 1

        if std_volume == 0:
            std_volume = mean_volume * 0.1 or 1

        # Calculate z-score for recent period
        recent_hourly_avg = recent_volume / recent_hours if recent_hours > 0 else 0
        z_score = (recent_hourly_avg - mean_volume) / std_volume

        if z_score < self.z_score_threshold:
            return None

        severity = self._calculate_severity(z_score, recent_volume, market)

        stats = VolumeStats(
            market_id=market.condition_id,
            current_volume=recent_volume,
            mean_volume=mean_volume * recent_hours,
            std_volume=std_volume * recent_hours,
            z_score=z_score,
            period_start=now - timedelta(hours=recent_hours),
            period_end=now,
        )

        return Alert(
            signal_type=SignalType.VOLUME_ANOMALY,
            severity=severity,
            market=market,
            description=f"Volume spike: {z_score:.1f}x standard deviation above normal",
            details={
                "z_score": z_score,
                "recent_volume_usd": recent_volume,
                "expected_volume_usd": mean_volume * recent_hours,
                "std_volume_usd": std_volume * recent_hours,
                "period_hours": recent_hours,
                "volume_multiplier": recent_volume / (mean_volume * recent_hours) if mean_volume > 0 else 0,
            },
            timestamp=now,
        )

    def _calculate_hourly_volumes(
        self, trades: list, start_time: datetime
    ) -> list[float]:
        """Calculate hourly trading volumes.

        Args:
            trades: List of trades
            start_time: Start of analysis period

        Returns:
            List of hourly volumes in USD
        """
        now = datetime.utcnow()
        hours = int((now - start_time).total_seconds() / 3600) + 1
        hourly_volumes = [0.0] * hours

        for trade in trades:
            if trade.timestamp < start_time:
                continue
            hour_index = int((trade.timestamp - start_time).total_seconds() / 3600)
            if 0 <= hour_index < len(hourly_volumes):
                hourly_volumes[hour_index] += trade.usd_value

        return hourly_volumes

    def _calculate_severity(
        self, z_score: float, volume: float, market: Market
    ) -> Severity:
        """Calculate alert severity."""
        score = 0

        # Z-score factor
        if z_score >= 6:
            score += 4
        elif z_score >= 5:
            score += 3
        elif z_score >= 4:
            score += 2
        elif z_score >= 3:
            score += 1

        # Absolute volume factor
        if volume >= 100000:
            score += 2
        elif volume >= 50000:
            score += 1

        # Market proximity to resolution
        if market.end_date:
            hours_to_end = (market.end_date - datetime.utcnow()).total_seconds() / 3600
            if 0 < hours_to_end <= 24:
                score += 2
            elif 0 < hours_to_end <= 72:
                score += 1

        if score >= 6:
            return Severity.CRITICAL
        elif score >= 4:
            return Severity.HIGH
        elif score >= 2:
            return Severity.MEDIUM
        return Severity.LOW
