"""Detector for coordinated wallet trading patterns."""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

import networkx as nx

from ..models import Alert, Market, Trade, Severity, SignalType, WalletCluster
from ..api.gamma import GammaClient
from ..api.data import DataClient


class WalletClusterDetector:
    """Detects groups of wallets trading in coordinated patterns."""

    def __init__(
        self,
        gamma_client: GammaClient,
        data_client: DataClient,
        time_window_minutes: int = 30,
        min_cluster_size: int = 3,
        min_shared_markets: int = 2,
        coordination_threshold: float = 0.7,
    ):
        """Initialize the detector.

        Args:
            gamma_client: Client for market data
            data_client: Client for trade data
            time_window_minutes: Window for considering trades as "coordinated"
            min_cluster_size: Minimum wallets to form a cluster
            min_shared_markets: Minimum markets traded together
            coordination_threshold: Min fraction of trades on same side
        """
        self.gamma = gamma_client
        self.data = data_client
        self.time_window_minutes = time_window_minutes
        self.min_cluster_size = min_cluster_size
        self.min_shared_markets = min_shared_markets
        self.coordination_threshold = coordination_threshold

    def scan(self, markets: Optional[list[Market]] = None) -> list[Alert]:
        """Scan markets for wallet clustering patterns.

        Args:
            markets: Markets to scan (defaults to high-volume markets)

        Returns:
            List of alerts for suspicious clusters
        """
        if markets is None:
            markets = self.gamma.get_high_volume_markets(limit=30)

        # Collect all trades across markets
        all_trades: list[Trade] = []
        for market in markets:
            trades = self.data.get_trades(market=market.condition_id, limit=1000)
            all_trades.extend(trades)

        if not all_trades:
            return []

        # Build wallet-market-side mapping
        wallet_activity = self._build_wallet_activity(all_trades)

        # Build co-trading graph
        graph = self._build_cotrade_graph(all_trades, wallet_activity)

        # Find clusters
        clusters = self._find_clusters(graph, wallet_activity)

        # Generate alerts
        alerts = []
        market_lookup = {m.condition_id: m for m in markets}

        for cluster in clusters:
            alert = self._create_cluster_alert(cluster, wallet_activity, market_lookup)
            if alert:
                alerts.append(alert)

        return sorted(alerts, key=lambda a: a.score, reverse=True)

    def _build_wallet_activity(
        self, trades: list[Trade]
    ) -> dict[str, dict[str, list[Trade]]]:
        """Build mapping of wallet -> market -> trades.

        Returns:
            Nested dict: wallet_activity[wallet][market_id] = [trades]
        """
        activity: dict[str, dict[str, list[Trade]]] = defaultdict(lambda: defaultdict(list))

        for trade in trades:
            activity[trade.wallet][trade.market_id].append(trade)

        return activity

    def _build_cotrade_graph(
        self,
        trades: list[Trade],
        wallet_activity: dict[str, dict[str, list[Trade]]],
    ) -> nx.Graph:
        """Build graph where wallets are connected if they trade together.

        Edges are weighted by:
        - Number of shared markets
        - Trading within time window
        - Same side trading

        Returns:
            NetworkX graph of wallet relationships
        """
        graph = nx.Graph()

        # Group trades by market and time bucket
        market_time_trades: dict[str, dict[int, list[Trade]]] = defaultdict(
            lambda: defaultdict(list)
        )

        bucket_size = self.time_window_minutes * 60  # seconds

        for trade in trades:
            bucket = int(trade.timestamp.timestamp() / bucket_size)
            market_time_trades[trade.market_id][bucket].append(trade)

        # Find co-trading relationships
        edge_weights: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"count": 0, "same_side": 0, "markets": set()}
        )

        for market_id, time_buckets in market_time_trades.items():
            for bucket, bucket_trades in time_buckets.items():
                wallets_in_bucket = defaultdict(list)
                for trade in bucket_trades:
                    wallets_in_bucket[trade.wallet].append(trade)

                wallet_list = list(wallets_in_bucket.keys())
                for i, w1 in enumerate(wallet_list):
                    for w2 in wallet_list[i + 1:]:
                        key = tuple(sorted([w1, w2]))
                        edge_weights[key]["count"] += 1
                        edge_weights[key]["markets"].add(market_id)

                        # Check if same side
                        w1_sides = {t.side for t in wallets_in_bucket[w1]}
                        w2_sides = {t.side for t in wallets_in_bucket[w2]}
                        if w1_sides & w2_sides:  # Intersection
                            edge_weights[key]["same_side"] += 1

        # Add edges to graph
        for (w1, w2), data in edge_weights.items():
            if len(data["markets"]) >= self.min_shared_markets:
                coordination = (
                    data["same_side"] / data["count"] if data["count"] > 0 else 0
                )
                if coordination >= self.coordination_threshold:
                    graph.add_edge(
                        w1,
                        w2,
                        weight=data["count"],
                        markets=data["markets"],
                        coordination=coordination,
                    )

        return graph

    def _find_clusters(
        self,
        graph: nx.Graph,
        wallet_activity: dict[str, dict[str, list[Trade]]],
    ) -> list[WalletCluster]:
        """Find wallet clusters using connected components.

        Returns:
            List of WalletCluster objects
        """
        clusters = []

        for component in nx.connected_components(graph):
            if len(component) < self.min_cluster_size:
                continue

            wallets = list(component)
            subgraph = graph.subgraph(wallets)

            # Calculate cluster metrics
            all_markets: set[str] = set()
            total_volume = 0.0
            all_timestamps: list[datetime] = []

            for wallet in wallets:
                for market_id, trades in wallet_activity[wallet].items():
                    all_markets.add(market_id)
                    for trade in trades:
                        total_volume += trade.usd_value
                        all_timestamps.append(trade.timestamp)

            # Calculate coordination score
            edge_coordinations = [
                d.get("coordination", 0) for _, _, d in subgraph.edges(data=True)
            ]
            avg_coordination = (
                sum(edge_coordinations) / len(edge_coordinations)
                if edge_coordinations
                else 0
            )

            if all_timestamps:
                cluster = WalletCluster(
                    wallets=wallets,
                    markets=list(all_markets),
                    total_volume=total_volume,
                    coordination_score=avg_coordination,
                    first_seen=min(all_timestamps),
                    last_seen=max(all_timestamps),
                )
                clusters.append(cluster)

        return clusters

    def _create_cluster_alert(
        self,
        cluster: WalletCluster,
        wallet_activity: dict[str, dict[str, list[Trade]]],
        market_lookup: dict[str, Market],
    ) -> Optional[Alert]:
        """Create an alert for a suspicious cluster."""
        if not cluster.markets:
            return None

        # Use first market for the alert (could enhance to show all)
        primary_market_id = cluster.markets[0]
        market = market_lookup.get(primary_market_id)
        if not market:
            return None

        severity = self._calculate_severity(cluster)

        # Collect relevant trades
        trades: list[Trade] = []
        for wallet in cluster.wallets:
            for market_id in cluster.markets:
                trades.extend(wallet_activity[wallet].get(market_id, []))

        return Alert(
            signal_type=SignalType.WALLET_CLUSTER,
            severity=severity,
            market=market,
            description=f"Cluster of {len(cluster.wallets)} wallets trading together across {len(cluster.markets)} markets",
            details={
                "cluster_size": len(cluster.wallets),
                "markets_count": len(cluster.markets),
                "total_volume_usd": cluster.total_volume,
                "coordination_score": cluster.coordination_score,
                "first_seen": cluster.first_seen.isoformat(),
                "last_seen": cluster.last_seen.isoformat(),
                "wallet_addresses": cluster.wallets[:10],  # Limit for display
            },
            trades=trades[:50],  # Limit for display
            wallets=cluster.wallets,
            timestamp=cluster.last_seen,
        )

    def _calculate_severity(self, cluster: WalletCluster) -> Severity:
        """Calculate severity based on cluster characteristics."""
        score = 0

        # Cluster size
        if len(cluster.wallets) >= 10:
            score += 3
        elif len(cluster.wallets) >= 5:
            score += 2
        elif len(cluster.wallets) >= 3:
            score += 1

        # Total volume
        if cluster.total_volume >= 100000:
            score += 3
        elif cluster.total_volume >= 50000:
            score += 2
        elif cluster.total_volume >= 10000:
            score += 1

        # Coordination score
        if cluster.coordination_score >= 0.9:
            score += 2
        elif cluster.coordination_score >= 0.8:
            score += 1

        # Markets involved
        if len(cluster.markets) >= 5:
            score += 2
        elif len(cluster.markets) >= 3:
            score += 1

        if score >= 8:
            return Severity.CRITICAL
        elif score >= 5:
            return Severity.HIGH
        elif score >= 3:
            return Severity.MEDIUM
        return Severity.LOW
