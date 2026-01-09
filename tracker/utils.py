"""Utility functions for formatting and display."""

from datetime import datetime, timedelta
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from .models import Alert, Market, Severity, SignalType


console = Console()


def format_usd(value: float) -> str:
    """Format a USD value with appropriate precision."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value / 1_000:.1f}K"
    else:
        return f"${value:.2f}"


def format_time_delta(delta: Optional[timedelta]) -> str:
    """Format a timedelta in human-readable form."""
    if delta is None:
        return "N/A"

    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "Expired"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours > 24:
        days = hours // 24
        hours = hours % 24
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def format_wallet(address: str, length: int = 10) -> str:
    """Truncate wallet address for display."""
    if len(address) <= length:
        return address
    half = (length - 4) // 2
    return f"{address[:half + 2]}...{address[-half:]}"


def severity_color(severity: Severity) -> str:
    """Get color for severity level."""
    colors = {
        Severity.LOW: "green",
        Severity.MEDIUM: "yellow",
        Severity.HIGH: "orange1",
        Severity.CRITICAL: "red bold",
    }
    return colors.get(severity, "white")


def signal_emoji(signal_type: SignalType) -> str:
    """Get emoji/symbol for signal type."""
    symbols = {
        SignalType.LARGE_TRADE_BEFORE_RESOLUTION: "[bold magenta]TRADE[/]",
        SignalType.WALLET_CLUSTER: "[bold cyan]CLUSTER[/]",
        SignalType.VOLUME_ANOMALY: "[bold yellow]VOLUME[/]",
    }
    return symbols.get(signal_type, "ALERT")


def print_alert(alert: Alert) -> None:
    """Print a formatted alert to console."""
    severity_style = severity_color(alert.severity)
    signal_label = signal_emoji(alert.signal_type)

    title = Text()
    title.append(f"[{alert.severity.value}] ", style=severity_style)
    title.append(signal_label)

    content_lines = [
        f"[bold]Market:[/] {alert.market.question[:80]}",
        f"[bold]Description:[/] {alert.description}",
    ]

    # Add relevant details based on signal type
    if alert.signal_type == SignalType.LARGE_TRADE_BEFORE_RESOLUTION:
        details = alert.details
        content_lines.extend([
            f"[bold]Wallet:[/] {format_wallet(details.get('wallet', 'Unknown'))}",
            f"[bold]Trade:[/] {format_usd(details.get('trade_usd', 0))} on {details.get('outcome', '?')}",
            f"[bold]Price:[/] {details.get('price', 0):.1%}",
            f"[bold]Size Percentile:[/] {details.get('percentile', 0):.1f}%",
        ])
        if details.get('time_to_resolution_hours'):
            content_lines.append(
                f"[bold]Time to Resolution:[/] {details['time_to_resolution_hours']:.1f}h"
            )

    elif alert.signal_type == SignalType.VOLUME_ANOMALY:
        details = alert.details
        content_lines.extend([
            f"[bold]Z-Score:[/] {details.get('z_score', 0):.1f}",
            f"[bold]Recent Volume:[/] {format_usd(details.get('recent_volume_usd', 0))}",
            f"[bold]Expected Volume:[/] {format_usd(details.get('expected_volume_usd', 0))}",
            f"[bold]Multiplier:[/] {details.get('volume_multiplier', 0):.1f}x",
        ])

    elif alert.signal_type == SignalType.WALLET_CLUSTER:
        details = alert.details
        content_lines.extend([
            f"[bold]Cluster Size:[/] {details.get('cluster_size', 0)} wallets",
            f"[bold]Markets:[/] {details.get('markets_count', 0)} markets",
            f"[bold]Total Volume:[/] {format_usd(details.get('total_volume_usd', 0))}",
            f"[bold]Coordination:[/] {details.get('coordination_score', 0):.0%}",
        ])

    content_lines.append(f"[dim]Detected: {alert.timestamp.strftime('%Y-%m-%d %H:%M UTC')}[/]")

    panel = Panel(
        "\n".join(content_lines),
        title=title,
        border_style=severity_style.split()[0],
        padding=(0, 1),
    )
    console.print(panel)
    console.print()


def print_alerts_summary(alerts: list[Alert]) -> None:
    """Print summary table of alerts."""
    if not alerts:
        console.print("[dim]No suspicious activity detected.[/]")
        return

    table = Table(title="Suspicious Activity Summary")
    table.add_column("Severity", style="bold")
    table.add_column("Type")
    table.add_column("Market")
    table.add_column("Details")
    table.add_column("Time")

    for alert in alerts[:20]:  # Limit to 20
        severity_style = severity_color(alert.severity)
        market_short = alert.market.question[:40] + ("..." if len(alert.market.question) > 40 else "")

        # Brief detail based on type
        if alert.signal_type == SignalType.LARGE_TRADE_BEFORE_RESOLUTION:
            detail = format_usd(alert.details.get("trade_usd", 0))
        elif alert.signal_type == SignalType.VOLUME_ANOMALY:
            detail = f"z={alert.details.get('z_score', 0):.1f}"
        else:
            detail = f"{alert.details.get('cluster_size', 0)} wallets"

        table.add_row(
            Text(alert.severity.value, style=severity_style),
            alert.signal_type.value.replace("_", " ").title()[:15],
            market_short,
            detail,
            alert.timestamp.strftime("%H:%M"),
        )

    console.print(table)


def print_market(market: Market) -> None:
    """Print market info."""
    time_remaining = None
    if market.end_date:
        time_remaining = market.end_date - datetime.utcnow()

    console.print(f"[bold]{market.question}[/]")
    console.print(f"  Slug: {market.slug}")
    console.print(f"  Volume: {format_usd(market.volume)} (24h: {format_usd(market.volume_24h)})")
    console.print(f"  Liquidity: {format_usd(market.liquidity)}")

    if market.outcomes and market.outcome_prices:
        prices = ", ".join(
            f"{o}: {p:.1%}" for o, p in zip(market.outcomes, market.outcome_prices)
        )
        console.print(f"  Prices: {prices}")

    if time_remaining:
        console.print(f"  Closes in: {format_time_delta(time_remaining)}")

    console.print()


def print_markets_table(markets: list[Market]) -> None:
    """Print table of markets."""
    table = Table(title="High Volume Markets")
    table.add_column("#", style="dim")
    table.add_column("Market")
    table.add_column("24h Volume", justify="right")
    table.add_column("Liquidity", justify="right")
    table.add_column("Closes In", justify="right")

    for i, market in enumerate(markets[:30], 1):
        time_remaining = None
        if market.end_date:
            time_remaining = market.end_date - datetime.utcnow()

        table.add_row(
            str(i),
            market.question[:50] + ("..." if len(market.question) > 50 else ""),
            format_usd(market.volume_24h),
            format_usd(market.liquidity),
            format_time_delta(time_remaining),
        )

    console.print(table)
