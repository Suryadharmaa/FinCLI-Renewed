"""Command parsing and routing."""

from __future__ import annotations

import logging

from rich.panel import Panel
from rich.table import Table

from fincli.app.cli.handlers.common import (
    _extract_option_value,
    _format_alert_checks,
    _format_alert_history,
    _format_alerts,
    _format_audit_log,
    _format_broker_account,
    _format_broker_orders,
    _format_broker_positions,
    _format_broker_status,
    _format_brokers,
    _format_connection_status,
    _format_live_order_result,
    _format_live_status,
    _format_live_trading_help,
    _format_order_confirmation,
    _format_paper_order,
    _format_paper_orders,
    _format_positions,
    _format_realtime_connectors,
    _format_risk_status,
    _format_stream_status,
    _format_trading_overview,
)
from fincli.app.cli.result import CommandResult
from fincli.app.modules.alerts import AlertCheckResult, evaluate_alert
from fincli.app.utils.errors import CommandError

logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class TradingCommands:
    """Trading command handlers."""

    def _notification(self, args: list[str]) -> CommandResult:
        """Manage webhook notifications (Discord/Telegram)."""
        from fincli.app.connectors.webhooks import (
            NotificationManager,
            configure_discord_webhook,
            configure_telegram_webhook,
            remove_webhook,
        )

        manager = NotificationManager(self.config)

        if not args:
            targets = manager.get_active_targets()
            if not targets:
                return CommandResult(
                    Panel(
                        (
                            "No notification targets configured.\n\n"
                            "Commands:\n"
                            "- /notification add discord <name> <webhook_url>\n"
                            "- /notification add telegram <name> <bot_token> <chat_id>\n"
                            "- /notification list\n"
                            "- /notification test <target>\n"
                            "- /notification remove <target>\n\n"
                            "Target format: discord:name or telegram:name"
                        ),
                        title="Notifications",
                    )
                )
            table = Table(title="Active Notification Targets", border_style="cyan")
            table.add_column("Target", style="bold")
            table.add_column("Type")
            table.add_column("Status")
            for target in targets:
                parts = target.split(":")
                table.add_row(target, parts[0].capitalize(), "✓ Configured")
            return CommandResult(table)

        action = args[0].lower()

        if action == "list":
            targets = manager.get_active_targets()
            if not targets:
                return CommandResult(
                    Panel("No notification targets configured.", title="Notifications", border_style="yellow")
                )
            table = Table(title="Notification Targets", border_style="cyan")
            table.add_column("Target", style="bold")
            table.add_column("Type")
            for target in targets:
                table.add_row(target, target.split(":")[0].capitalize())
            return CommandResult(table)

        if action == "add":
            if len(args) < 3:
                raise CommandError("Format: /notification add discord|telegram <name> ...")
            webhook_type = args[1].lower()
            name = args[2].lower()
            if webhook_type == "discord":
                if len(args) < 4:
                    raise CommandError("Format: /notification add discord <name> <webhook_url>")
                configure_discord_webhook(name, args[3])
                return CommandResult(
                    Panel(f"Discord webhook '{name}' configured.", title="Notification Added", border_style="green")
                )
            if webhook_type == "telegram":
                if len(args) < 5:
                    raise CommandError("Format: /notification add telegram <name> <bot_token> <chat_id>")
                configure_telegram_webhook(name, args[3], args[4])
                return CommandResult(
                    Panel(f"Telegram webhook '{name}' configured.", title="Notification Added", border_style="green")
                )
            raise CommandError(f"Unsupported webhook type: {webhook_type}. Use 'discord' or 'telegram'.")

        if action == "test":
            if len(args) < 2:
                raise CommandError("Format: /notification test <target>\nTarget format: discord:name or telegram:name")
            target = args[1]
            success, error = manager.test_notification(target)
            if success:
                return CommandResult(
                    Panel(f"Test notification sent to {target} ✅", title="Notification Test", border_style="green")
                )
            return CommandResult(
                Panel(
                    f"Failed to send test notification to {target} ❌\n\nError: {error}",
                    title="Notification Test",
                    border_style="red",
                )
            )

        if action == "remove":
            if len(args) < 2:
                raise CommandError("Format: /notification remove <target>")
            target = args[1]
            if remove_webhook(target):
                return CommandResult(Panel(f"Removed {target}", title="Notification Removed", border_style="green"))
            return CommandResult(Panel(f"Failed to remove {target}", title="Notification Remove", border_style="red"))

        raise CommandError("Unknown notification action. Use: list, add, test, remove")

    def _alert(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            return CommandResult(_format_alerts(self.alerts.list()))
        if action == "add":
            if len(args) < 4:
                raise CommandError(
                    "Format: /alert add <symbol> <above|below|rsi_below|rsi_above|volume_above|macd_cross_up|macd_cross_down> <target> [note]"
                )
            symbol = args[1]
            condition = args[2]
            try:
                target = float(args[3])
            except ValueError as exc:
                raise CommandError("Alert target must be a number.") from exc
            note = " ".join(args[4:]).strip()
            self.alerts.add(symbol, condition, target, note)
            return CommandResult(Panel(f"Alert ditambahkan: {symbol.upper()} {condition} {target:g}", title="Alert"))
        if action in {"remove", "delete", "rm"}:
            if len(args) < 2:
                raise CommandError("Format: /alert remove <id>")
            self.alerts.remove(int(args[1]))
            return CommandResult(Panel(f"Alert deleted: {args[1]}", title="Alert"))
        if action == "check":
            checked: list[AlertCheckResult] = []
            for alert in self.alerts.list(active_only=True):
                quote = self._safe_quote(str(alert["symbol"]))
                result = evaluate_alert(alert, quote.price if quote else None)
                checked.append(result)
                if result.triggered:
                    self.alerts.mark_triggered(result.id)
                    self.alerts.record_history(
                        result.id,
                        result.symbol,
                        result.condition,
                        result.target,
                        result.current_price,
                        True,
                        result.note,
                    )
            return CommandResult(_format_alert_checks(checked))
        if action == "history":
            return CommandResult(_format_alert_history(self.alerts.get_history()))
        if action == "daemon":
            return self._alert_daemon(args[1:])
        raise CommandError(
            "Format: /alert, /alert add <symbol> <condition> <target>, /alert remove <id>, /alert check, "
            "/alert history, /alert daemon start|stop|status"
        )

    def _alert_daemon(self, args: list[str]) -> CommandResult:
        if not hasattr(self, "_alert_daemon_instance"):
            from fincli.app.modules.alerts import AlertDaemon

            self._alert_daemon_instance = AlertDaemon(self.alerts, self.market_service, check_interval=60.0)

        daemon = self._alert_daemon_instance
        action = args[0].lower() if args else "status"

        if action == "start":
            if daemon.is_running:
                return CommandResult(Panel("Alert daemon is already running.", title="Alert Daemon"))
            daemon.start()
            return CommandResult(
                Panel(
                    "Alert daemon started. Checking every 60s. Use /alert daemon stop to halt.",
                    title="Alert Daemon",
                    border_style="green",
                )
            )
        if action == "stop":
            if not daemon.is_running:
                return CommandResult(Panel("Alert daemon is not running.", title="Alert Daemon"))
            daemon.stop()
            return CommandResult(Panel("Alert daemon stopped.", title="Alert Daemon", border_style="yellow"))
        if action == "status":
            status = "running" if daemon.is_running else "stopped"
            last = daemon.last_check.isoformat() if daemon.last_check else "never"
            return CommandResult(
                Panel(
                    f"Status: {status}\nLast check: {last}\nTriggered this session: {daemon.triggered_count}\nInterval: {daemon.check_interval}s",
                    title="Alert Daemon",
                )
            )
        raise CommandError("Format: /alert daemon start|stop|status")

    def _trading(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(
                _format_trading_overview(self.realtime_connector_catalog, self.broker_catalog, self.paper_trading)
            )
        action = args[0].lower()
        if action in {"realtime", "feeds", "feed"}:
            return CommandResult(_format_realtime_connectors(self.realtime_connector_catalog.all()))
        if action in {"brokers", "broker"}:
            return self._trading_broker(args[1:])
        if action == "paper":
            return self._trading_paper(args[1:])
        if action == "kill":
            self.paper_trading.set_kill_switch(True, "Manual kill switch via /trading kill")
            return CommandResult(
                Panel(
                    "Kill switch ACTIVATED. All paper orders blocked. Use /trading resume to re-enable.",
                    title="Trading",
                    border_style="red",
                )
            )
        if action == "resume":
            self.paper_trading.set_kill_switch(False)
            return CommandResult(
                Panel("Kill switch deactivated. Paper orders re-enabled.", title="Trading", border_style="green")
            )
        if action == "risk":
            return CommandResult(_format_risk_status(self.paper_trading))
        if action == "audit":
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 50
            return CommandResult(_format_audit_log(self.paper_trading.audit.list_entries(limit)))
        if action == "cancel":
            if len(args) < 2:
                raise CommandError("Format: /trading cancel <order_id>")
            order = self.paper_trading.cancel_order(int(args[1]))
            return CommandResult(_format_paper_order(order))
        if action == "positions":
            return CommandResult(_format_positions(self.paper_trading.get_positions()))
        if action == "stream":
            return self._trading_stream(args[1:])
        if action == "live":
            return self._trading_live(args[1:])
        raise CommandError(
            "Format: /trading, /trading realtime, /trading brokers, /trading broker use|status, "
            "/trading paper buy|sell|orders|positions|cancel, /trading kill, /trading resume, "
            "/trading risk, /trading audit, /trading stream"
        )

    def _trading_broker(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_brokers(self.broker_catalog.all()))
        action = args[0].lower()
        if action == "use":
            if len(args) < 2:
                raise CommandError("Format: /trading broker use <name>")
            return CommandResult(
                Panel(
                    f"Broker adapter '{args[1]}' is catalog-level. "
                    f"Configure API keys via /news_model key or environment variables, then use /trading paper --live to route through the adapter.",
                    title="Broker Adapter",
                    border_style="yellow",
                )
            )
        if action == "status":
            return CommandResult(_format_broker_status(self.broker_catalog))
        raise CommandError("Format: /trading brokers, /trading broker use <name>, /trading broker status")

    def _trading_paper(self, args: list[str]) -> CommandResult:
        if not args or args[0].lower() in {"orders", "list"}:
            return CommandResult(_format_paper_orders(self.paper_trading.list_orders()))
        if args[0].lower() == "positions":
            return CommandResult(_format_positions(self.paper_trading.get_positions()))
        if len(args) < 4:
            raise CommandError(
                "Format: /trading paper <buy|sell> <symbol> <qty> <market|limit|stop_limit> [price] [--stop <price>]"
            )
        side = args[0].lower()
        symbol = args[1].upper()
        try:
            quantity = float(args[2])
            price = float(args[4]) if len(args) >= 5 and not args[4].startswith("--") else None
            stop_raw = _extract_option_value(args, "--stop")
            stop_price = float(stop_raw) if stop_raw is not None else None
        except ValueError as exc:
            raise CommandError("Quantity, price, and stop price must be numbers.") from exc
        order_type = args[3].lower()
        if self.paper_trading.is_kill_switch_active():
            self.paper_trading.audit.record(
                "risk_blocked", f"{side} {symbol} {quantity} {order_type}: Kill switch active"
            )
            raise CommandError("Kill switch active: paper order blocked before quote lookup.")
        quote = self._safe_quote(symbol)
        if quote is not None and quote.price is not None:
            self.paper_trading.process_market_price(symbol, quote.price)
        if order_type == "market":
            if quote is None or quote.price is None or quote.price <= 0:
                raise CommandError("Paper market order requires a valid reference price from the quote provider.")
            price = quote.price
        order = self.paper_trading.place_order(side, symbol, quantity, order_type, price=price, stop_price=stop_price)
        return CommandResult(_format_paper_order(order))

    def _trading_stream(self, args: list[str]) -> CommandResult:
        if not args:
            connectors = self.realtime_connector_catalog.all()
            return CommandResult(_format_stream_status(connectors))
        connector = args[0].lower()
        return CommandResult(
            Panel(
                f"Stream '{connector}' — connect via the realtime_stream module adapters "
                f"(KrakenWebSocketAdapter, HyperLiquidWebSocketAdapter, EquityStreamingAdapter). "
                f"See /trading realtime for available connectors.",
                title="Stream",
                border_style="cyan",
            )
        )

    def _trading_live(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_live_trading_help())

        action = args[0].lower()

        if action == "status":
            return CommandResult(_format_live_status(self.live_trading))

        if action == "connect":
            if len(args) < 2:
                raise CommandError("Format: /trading live connect <broker> [paper|live]")
            broker_name = args[1].lower()
            mode = args[2].lower() if len(args) >= 3 else "paper"
            from fincli.app.brokers.registry import BrokerRegistry

            if not hasattr(self, "_broker_registry"):
                self._broker_registry = BrokerRegistry()
            status = self._run_async(self._broker_registry.connect(broker_name, mode))
            if status.connected:
                self.live_trading.set_broker(self._broker_registry.active_broker, mode)
            return CommandResult(_format_connection_status(status))

        if action == "disconnect":
            if hasattr(self, "_broker_registry"):
                self._run_async(self._broker_registry.disconnect())
            self.live_trading.set_broker(None)
            return CommandResult(Panel("Broker disconnected.", title="Live Trading", border_style="yellow"))

        if action == "account":
            account = self._run_async(self.live_trading.get_account())
            return CommandResult(_format_broker_account(account))

        if action == "positions":
            positions = self._run_async(self.live_trading.get_positions())
            return CommandResult(_format_broker_positions(positions))

        if action == "orders":
            status_filter = args[1] if len(args) >= 2 else None
            orders = self._run_async(self.live_trading.list_orders(status=status_filter))
            return CommandResult(_format_broker_orders(orders))

        if action in {"buy", "sell"}:
            if len(args) < 3:
                raise CommandError(f"Format: /trading live {action} <symbol> <quantity> [--confirm] [--price <price>]")
            symbol = args[1].upper()
            quantity = float(args[2])
            confirm = "--confirm" in args
            price = None
            if "--price" in args:
                price_idx = args.index("--price")
                if price_idx + 1 < len(args):
                    price = float(args[price_idx + 1])
            order_type = "limit" if price else "market"

            if not confirm:
                quote = self._safe_quote(symbol)
                # Show confirmation prompt
                confirmation = self.live_trading.build_confirmation(
                    symbol=symbol,
                    side=action,
                    quantity=quantity,
                    order_type=order_type,
                    price=price,
                    current_price=quote.price if quote is not None and quote.price is not None else 0.0,
                )
                return CommandResult(_format_order_confirmation(confirmation))

            # Place order with confirmation
            quote = self._safe_quote(symbol)
            if order_type == "market" and (quote is None or quote.price is None or quote.price <= 0):
                raise CommandError("Live market order requires a valid reference price from the quote provider.")
            result = self._run_async(
                self.live_trading.place_order(
                    symbol=symbol,
                    side=action,
                    quantity=quantity,
                    order_type=order_type,
                    price=price,
                    reference_price=quote.price if quote is not None else None,
                )
            )
            return CommandResult(_format_live_order_result(result))

        if action == "cancel":
            if len(args) < 2:
                raise CommandError("Format: /trading live cancel <broker_order_id>")
            result = self._run_async(self.live_trading.cancel_order(args[1]))
            return CommandResult(
                _format_live_order_result(
                    {
                        "broker_order_id": result.broker_order_id,
                        "symbol": result.symbol,
                        "side": result.side,
                        "status": result.status,
                        "broker": result.broker,
                    }
                )
            )

        raise CommandError("Format: /trading live status|connect|disconnect|buy|sell|positions|orders|account|cancel")
