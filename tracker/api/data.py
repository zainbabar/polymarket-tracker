"""Data API client for fetching trades and positions."""

import httpx
from datetime import datetime
from typing import Optional

from ..models import Trade, Side

BASE_URL = "https://data-api.polymarket.com"


class DataClient:
    """Client for Polymarket Data API."""

    def __init__(self, timeout: float = 30.0):
        self.client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def get_trades(
        self,
        market: Optional[str] = None,
        user: Optional[str] = None,
        side: Optional[str] = None,
        min_amount: Optional[float] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[Trade]:
        """Fetch trades from Data API.

        Args:
            market: Condition ID to filter by
            user: Wallet address to filter by
            side: BUY or SELL
            min_amount: Minimum trade size in USD
            limit: Max results (max 10000)
            offset: Pagination offset

        Returns:
            List of Trade objects
        """
        params = {"limit": min(limit, 10000), "offset": offset}

        if market:
            params["market"] = market
        if user:
            params["user"] = user
        if side:
            params["side"] = side
        if min_amount:
            params["filterType"] = "CASH"
            params["filterAmount"] = min_amount

        response = self.client.get("/trades", params=params)
        response.raise_for_status()
        data = response.json()

        trades = []
        for item in data:
            trade = self._parse_trade(item)
            if trade:
                trades.append(trade)

        return trades

    def get_trades_for_markets(
        self, market_ids: list[str], limit_per_market: int = 500
    ) -> list[Trade]:
        """Fetch trades for multiple markets.

        Args:
            market_ids: List of condition IDs
            limit_per_market: Max trades per market

        Returns:
            List of trades across all markets
        """
        all_trades = []
        for market_id in market_ids:
            trades = self.get_trades(market=market_id, limit=limit_per_market)
            all_trades.extend(trades)
        return all_trades

    def get_large_trades(
        self, market: str, min_usd: float = 1000, limit: int = 500
    ) -> list[Trade]:
        """Get large trades for a specific market.

        Args:
            market: Condition ID
            min_usd: Minimum trade value in USD
            limit: Max results

        Returns:
            List of large trades
        """
        return self.get_trades(market=market, min_amount=min_usd, limit=limit)

    def get_wallet_trades(
        self, wallet: str, limit: int = 1000
    ) -> list[Trade]:
        """Get all trades for a specific wallet.

        Args:
            wallet: Wallet address (0x prefixed)
            limit: Max results

        Returns:
            List of trades by this wallet
        """
        return self.get_trades(user=wallet, limit=limit)

    def get_holders(
        self, market: str, limit: int = 100
    ) -> list[dict]:
        """Get top position holders for a market.

        Args:
            market: Condition ID
            limit: Max results

        Returns:
            List of holder data with wallet and position info
        """
        params = {"market": market, "limit": limit}
        response = self.client.get("/holders", params=params)
        response.raise_for_status()
        return response.json()

    def get_positions(
        self,
        user: Optional[str] = None,
        market: Optional[str] = None,
        min_size: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get positions data.

        Args:
            user: Wallet address
            market: Condition ID
            min_size: Minimum position size
            limit: Max results

        Returns:
            List of position data
        """
        params = {"limit": limit}
        if user:
            params["user"] = user
        if market:
            params["market"] = market
        if min_size:
            params["sizeThreshold"] = min_size

        response = self.client.get("/positions", params=params)
        response.raise_for_status()
        return response.json()

    def _parse_trade(self, data: dict) -> Optional[Trade]:
        """Parse API response into Trade model."""
        try:
            timestamp = datetime.fromtimestamp(data["timestamp"])
            size = float(data.get("size", 0))
            price = float(data.get("price", 0))
            usd_value = size * price

            return Trade(
                transaction_hash=data.get("transactionHash", ""),
                wallet=data.get("proxyWallet", data.get("user", "")),
                market_id=data.get("conditionId", ""),
                market_slug=data.get("slug", ""),
                market_question=data.get("title", ""),
                side=Side(data.get("side", "BUY")),
                outcome=data.get("outcome", ""),
                outcome_index=int(data.get("outcomeIndex", 0)),
                size=size,
                price=price,
                usd_value=usd_value,
                timestamp=timestamp,
            )
        except Exception:
            return None
