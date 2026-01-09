"""Gamma API client for fetching market data."""

import httpx
from datetime import datetime
from typing import Optional

from ..models import Market

BASE_URL = "https://gamma-api.polymarket.com"


class GammaClient:
    """Client for Polymarket Gamma API."""

    def __init__(self, timeout: float = 30.0):
        self.client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[Market]:
        """Fetch markets from Gamma API.

        Args:
            active: Include active markets
            closed: Include closed markets
            limit: Max results per request
            offset: Pagination offset
            order: Sort field (volume24hr, volume, liquidity, endDate)
            ascending: Sort direction

        Returns:
            List of Market objects
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": str(ascending).lower(),
        }

        response = self.client.get("/markets", params=params)
        response.raise_for_status()
        data = response.json()

        markets = []
        for item in data:
            market = self._parse_market(item)
            if market:
                markets.append(market)

        return markets

    def get_market(self, condition_id: str) -> Optional[Market]:
        """Fetch a single market by condition ID."""
        response = self.client.get(f"/markets/{condition_id}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self._parse_market(response.json())

    def get_market_by_slug(self, slug: str) -> Optional[Market]:
        """Fetch a market by its slug."""
        params = {"slug": slug}
        response = self.client.get("/markets", params=params)
        response.raise_for_status()
        data = response.json()
        if data:
            return self._parse_market(data[0])
        return None

    def get_high_volume_markets(
        self, min_volume_24h: float = 10000, limit: int = 50
    ) -> list[Market]:
        """Get markets with high 24h trading volume.

        Args:
            min_volume_24h: Minimum 24h volume in USD
            limit: Max number of markets

        Returns:
            List of high-volume markets sorted by 24h volume
        """
        markets = self.get_markets(
            active=True, limit=limit, order="volume24hr", ascending=False
        )
        return [m for m in markets if m.volume_24h >= min_volume_24h]

    def get_markets_closing_soon(
        self, hours: int = 24, limit: int = 50
    ) -> list[Market]:
        """Get active markets closing within specified hours.

        Args:
            hours: Time window in hours
            limit: Max number of markets

        Returns:
            List of markets closing soon
        """
        from datetime import timedelta

        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours)

        markets = self.get_markets(active=True, limit=200, order="endDate", ascending=True)

        closing_soon = []
        for m in markets:
            if m.end_date and now < m.end_date <= cutoff:
                closing_soon.append(m)
            if len(closing_soon) >= limit:
                break

        return closing_soon

    def _parse_market(self, data: dict) -> Optional[Market]:
        """Parse API response into Market model."""
        try:
            end_date = None
            if data.get("endDate"):
                try:
                    # Parse and convert to naive UTC datetime for consistency
                    dt = datetime.fromisoformat(
                        data["endDate"].replace("Z", "+00:00")
                    )
                    end_date = dt.replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass

            outcomes = []
            outcome_prices = []
            if data.get("outcomes"):
                raw_outcomes = data["outcomes"]
                if isinstance(raw_outcomes, str):
                    import json
                    outcomes = json.loads(raw_outcomes)
                else:
                    outcomes = raw_outcomes
            if data.get("outcomePrices"):
                raw_prices = data["outcomePrices"]
                if isinstance(raw_prices, str):
                    import json
                    raw_prices = json.loads(raw_prices)
                try:
                    outcome_prices = [float(p) for p in raw_prices]
                except (ValueError, TypeError):
                    outcome_prices = []

            return Market(
                condition_id=data.get("conditionId", data.get("id", "")),
                question=data.get("question", ""),
                slug=data.get("slug", ""),
                end_date=end_date,
                volume=float(data.get("volume", 0) or 0),
                volume_24h=float(data.get("volume24hr", 0) or 0),
                liquidity=float(data.get("liquidity", 0) or 0),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                active=data.get("active", True),
            )
        except Exception:
            return None
