"""CLI entry point for Polymarket insider trading tracker."""

import argparse
import sys
import time
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from .api import GammaClient, DataClient
from .detectors import LargeTradeDetector, VolumeAnomalyDetector, WalletClusterDetector
from .utils import (
    console,
    print_alert,
    print_alerts_summary,
    print_market,
    print_markets_table,
    format_usd,
    format_wallet,
)

VERSION = "0.1.0"


def create_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="polymarket-tracker",
        description="Detect suspicious trading patterns on Polymarket",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {VERSION}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan command
    scan_parser = subparsers.add_parser(
        "scan", help="Scan high-volume markets for suspicious activity"
    )
    scan_parser.add_argument(
        "--min-volume",
        type=float,
        default=10000,
        help="Minimum 24h volume in USD (default: 10000)",
    )
    scan_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max markets to scan (default: 20)",
    )
    scan_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output for each alert",
    )

    # analyze command
    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze a specific market"
    )
    analyze_parser.add_argument(
        "market",
        help="Market slug or condition ID",
    )
    analyze_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output",
    )

    # wallet command
    wallet_parser = subparsers.add_parser(
        "wallet", help="Track a specific wallet's activity"
    )
    wallet_parser.add_argument(
        "address",
        help="Wallet address (0x prefixed)",
    )
    wallet_parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max trades to fetch (default: 100)",
    )

    # markets command
    markets_parser = subparsers.add_parser(
        "markets", help="List high-volume markets"
    )
    markets_parser.add_argument(
        "--min-volume",
        type=float,
        default=10000,
        help="Minimum 24h volume in USD (default: 10000)",
    )
    markets_parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max markets to show (default: 30)",
    )

    # watch command
    watch_parser = subparsers.add_parser(
        "watch", help="Continuously monitor for suspicious activity"
    )
    watch_parser.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Minutes between scans (default: 15)",
    )
    watch_parser.add_argument(
        "--min-volume",
        type=float,
        default=10000,
        help="Minimum 24h volume in USD (default: 10000)",
    )

    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute scan command."""
    console.print(f"[bold]Scanning for suspicious activity...[/]\n")

    with GammaClient() as gamma, DataClient() as data:
        # Get high-volume markets
        with console.status("Fetching high-volume markets..."):
            markets = gamma.get_high_volume_markets(
                min_volume_24h=args.min_volume, limit=args.limit
            )

        if not markets:
            console.print("[yellow]No markets found matching criteria.[/]")
            return 0

        console.print(f"Found {len(markets)} markets to analyze\n")

        # Initialize detectors
        large_trade_detector = LargeTradeDetector(gamma, data)
        volume_detector = VolumeAnomalyDetector(gamma, data)
        cluster_detector = WalletClusterDetector(gamma, data)

        all_alerts = []

        # Run detectors
        with console.status("Analyzing large trades..."):
            alerts = large_trade_detector.scan(markets)
            all_alerts.extend(alerts)
            console.print(f"  Large trades: {len(alerts)} alerts")

        with console.status("Analyzing volume anomalies..."):
            alerts = volume_detector.scan(markets)
            all_alerts.extend(alerts)
            console.print(f"  Volume anomalies: {len(alerts)} alerts")

        with console.status("Analyzing wallet clusters..."):
            alerts = cluster_detector.scan(markets)
            all_alerts.extend(alerts)
            console.print(f"  Wallet clusters: {len(alerts)} alerts")

        console.print()

        # Sort by severity
        all_alerts.sort(key=lambda a: a.score, reverse=True)

        if args.verbose:
            for alert in all_alerts:
                print_alert(alert)
        else:
            print_alerts_summary(all_alerts)

    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    """Execute analyze command."""
    with GammaClient() as gamma, DataClient() as data:
        # Find market
        with console.status(f"Finding market '{args.market}'..."):
            market = gamma.get_market_by_slug(args.market)
            if not market:
                market = gamma.get_market(args.market)

        if not market:
            console.print(f"[red]Market not found: {args.market}[/]")
            return 1

        console.print("[bold]Market Info[/]")
        print_market(market)

        # Run all detectors on this market
        large_trade_detector = LargeTradeDetector(gamma, data)
        volume_detector = VolumeAnomalyDetector(gamma, data)

        all_alerts = []

        with console.status("Analyzing..."):
            alerts = large_trade_detector.analyze_market(market)
            all_alerts.extend(alerts)

            alert = volume_detector.analyze_market(market)
            if alert:
                all_alerts.append(alert)

        all_alerts.sort(key=lambda a: a.score, reverse=True)

        if all_alerts:
            console.print(f"[bold]Found {len(all_alerts)} suspicious signals[/]\n")
            if args.verbose:
                for alert in all_alerts:
                    print_alert(alert)
            else:
                print_alerts_summary(all_alerts)
        else:
            console.print("[green]No suspicious activity detected.[/]")

    return 0


def cmd_wallet(args: argparse.Namespace) -> int:
    """Execute wallet command."""
    address = args.address
    if not address.startswith("0x"):
        console.print("[red]Invalid wallet address (must start with 0x)[/]")
        return 1

    with DataClient() as data:
        with console.status(f"Fetching trades for {format_wallet(address)}..."):
            trades = data.get_wallet_trades(address, limit=args.limit)

        if not trades:
            console.print(f"[yellow]No trades found for wallet {format_wallet(address)}[/]")
            return 0

        console.print(f"[bold]Wallet: {format_wallet(address, 20)}[/]")
        console.print(f"Found {len(trades)} recent trades\n")

        # Group by market
        from collections import defaultdict
        by_market: dict[str, list] = defaultdict(list)
        for trade in trades:
            by_market[trade.market_question[:50]].append(trade)

        for market_name, market_trades in by_market.items():
            total_volume = sum(t.usd_value for t in market_trades)
            console.print(f"[bold]{market_name}[/]")
            console.print(f"  Trades: {len(market_trades)}, Volume: {format_usd(total_volume)}")

            for trade in market_trades[:5]:
                side_color = "green" if trade.side.value == "BUY" else "red"
                console.print(
                    f"    [{side_color}]{trade.side.value}[/] {trade.outcome} "
                    f"@ {trade.price:.1%} ({format_usd(trade.usd_value)}) "
                    f"[dim]{trade.timestamp.strftime('%m/%d %H:%M')}[/]"
                )

            if len(market_trades) > 5:
                console.print(f"    [dim]... and {len(market_trades) - 5} more[/]")
            console.print()

    return 0


def cmd_markets(args: argparse.Namespace) -> int:
    """Execute markets command."""
    with GammaClient() as gamma:
        with console.status("Fetching markets..."):
            markets = gamma.get_high_volume_markets(
                min_volume_24h=args.min_volume, limit=args.limit
            )

        if not markets:
            console.print("[yellow]No markets found matching criteria.[/]")
            return 0

        print_markets_table(markets)

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Execute watch command - continuous monitoring."""
    interval_seconds = args.interval * 60
    seen_alerts: set[str] = set()

    console.print(f"[bold]Starting continuous monitoring[/]")
    console.print(f"Interval: {args.interval} minutes")
    console.print(f"Min volume: {format_usd(args.min_volume)}")
    console.print("Press Ctrl+C to stop\n")

    try:
        while True:
            scan_time = datetime.utcnow()
            console.print(f"[dim]Scan started at {scan_time.strftime('%H:%M:%S UTC')}[/]")

            with GammaClient() as gamma, DataClient() as data:
                markets = gamma.get_high_volume_markets(
                    min_volume_24h=args.min_volume, limit=20
                )

                if not markets:
                    console.print("[yellow]No markets to monitor[/]")
                else:
                    large_trade_detector = LargeTradeDetector(gamma, data)
                    volume_detector = VolumeAnomalyDetector(gamma, data)
                    cluster_detector = WalletClusterDetector(gamma, data)

                    all_alerts = []
                    all_alerts.extend(large_trade_detector.scan(markets))
                    all_alerts.extend(volume_detector.scan(markets))
                    all_alerts.extend(cluster_detector.scan(markets))

                    # Filter to new alerts only
                    new_alerts = []
                    for alert in all_alerts:
                        alert_key = f"{alert.signal_type}:{alert.market.condition_id}:{alert.description}"
                        if alert_key not in seen_alerts:
                            seen_alerts.add(alert_key)
                            new_alerts.append(alert)

                    if new_alerts:
                        console.print(f"\n[bold red]NEW ALERTS ({len(new_alerts)})[/]\n")
                        for alert in sorted(new_alerts, key=lambda a: a.score, reverse=True):
                            print_alert(alert)
                    else:
                        console.print("[dim]No new suspicious activity[/]")

            console.print(f"[dim]Next scan in {args.interval} minutes...[/]\n")
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped.[/]")
        return 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "scan": cmd_scan,
        "analyze": cmd_analyze,
        "wallet": cmd_wallet,
        "markets": cmd_markets,
        "watch": cmd_watch,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        try:
            return cmd_func(args)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/]")
            return 130
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
