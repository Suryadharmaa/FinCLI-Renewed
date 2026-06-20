"""Webhook notification system for Discord and Telegram."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx

from fincli.app.storage.config import ConfigManager
from fincli.app.storage.secrets import read_secrets, save_secret
from fincli.app.utils.errors import CommandError


# ---------------------------------------------------------------------------
# Webhook types
# ---------------------------------------------------------------------------


class WebhookType(str, Enum):
    DISCORD = "discord"
    TELEGRAM = "telegram"


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    webhook_type: WebhookType
    name: str
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    body: str
    severity: str = "info"  # info, warning, alert
    symbol: str = ""
    price: float | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(self, "timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))


# ---------------------------------------------------------------------------
# Discord webhook
# ---------------------------------------------------------------------------


def send_discord_notification(webhook_url: str, message: NotificationMessage) -> tuple[bool, str]:
    """Send notification to Discord via webhook. Returns (success, error_message)."""
    severity_colors = {
        "info": 0x3498DB,      # Blue
        "warning": 0xF39C12,   # Orange
        "alert": 0xE74C3C,     # Red
    }
    severity_emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "alert": "🚨",
    }

    embed = {
        "title": f"{severity_emoji.get(message.severity, '📊')} {message.title}",
        "description": message.body,
        "color": severity_colors.get(message.severity, 0x95A5A6),
        "footer": {"text": f"FinCLI • {message.timestamp}"},
    }

    if message.symbol:
        embed["fields"] = [{"name": "Symbol", "value": message.symbol, "inline": True}]
    if message.price is not None:
        if "fields" not in embed:
            embed["fields"] = []
        embed["fields"].append({"name": "Price", "value": f"{message.price:.2f}", "inline": True})

    payload = {"embeds": [embed]}

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(webhook_url, json=payload)
            if resp.status_code in (200, 204):
                return True, ""
            error_detail = resp.text[:200] if resp.text else "no response body"
            return False, f"HTTP {resp.status_code}: {error_detail}"
    except httpx.TimeoutException:
        return False, "Connection timeout (15s)"
    except httpx.ConnectError as exc:
        return False, f"Connection failed: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------


def send_telegram_notification(bot_token: str, chat_id: str, message: NotificationMessage) -> tuple[bool, str]:
    """Send notification to Telegram via Bot API. Returns (success, error_message)."""
    severity_emoji = {
        "info": "ℹ️",
        "warning": "⚠️",
        "alert": "🚨",
    }

    lines = [
        f"{severity_emoji.get(message.severity, '📊')} *{message.title}*",
        "",
        message.body,
    ]

    if message.symbol:
        lines.append(f"\n📊 Symbol: `{message.symbol}`")
    if message.price is not None:
        lines.append(f"💰 Price: `{message.price:.2f}`")

    lines.append(f"\n_{message.timestamp}_")

    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return True, ""
            error_msg = data.get("description", "unknown error")
            return False, f"Telegram API error: {error_msg}"
    except httpx.TimeoutException:
        return False, "Connection timeout (15s)"
    except httpx.ConnectError as exc:
        return False, f"Connection failed: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Notification manager
# ---------------------------------------------------------------------------


class NotificationManager:
    """Manage webhook configurations and send notifications."""

    def __init__(self, config: ConfigManager | None = None) -> None:
        self.config = config or ConfigManager()

    def _get_webhook_url(self, name: str) -> str | None:
        """Get Discord webhook URL from secrets."""
        secrets = read_secrets()
        return secrets.get(f"DISCORD_WEBHOOK_{name.upper()}")

    def _get_telegram_config(self, name: str) -> tuple[str, str] | None:
        """Get Telegram bot token and chat ID from secrets."""
        secrets = read_secrets()
        token = secrets.get(f"TELEGRAM_BOT_TOKEN_{name.upper()}")
        chat_id = secrets.get(f"TELEGRAM_CHAT_ID_{name.upper()}")
        if token and chat_id:
            return token, chat_id
        return None

    def send(self, target: str, message: NotificationMessage) -> tuple[bool, str]:
        """Send notification to a named webhook target.

        Target format: 'discord:name' or 'telegram:name'
        Returns (success, error_message).
        """
        parts = target.split(":", 1)
        if len(parts) != 2:
            return False, f"Invalid target format '{target}'. Use 'discord:name' or 'telegram:name'."

        webhook_type, name = parts[0].lower(), parts[1]

        if webhook_type == "discord":
            url = self._get_webhook_url(name)
            if not url:
                return False, f"Discord webhook '{name}' not found. Configure with /notification add discord {name} <url>"
            return send_discord_notification(url, message)

        if webhook_type == "telegram":
            tg_config = self._get_telegram_config(name)
            if not tg_config:
                return False, f"Telegram config '{name}' not found. Configure with /notification add telegram {name} <token> <chat_id>"
            token, chat_id = tg_config
            return send_telegram_notification(token, chat_id, message)

        return False, f"Unknown webhook type '{webhook_type}'. Use 'discord' or 'telegram'."

    def send_alert(self, symbol: str, condition: str, price: float, targets: list[str] | None = None) -> dict[str, tuple[bool, str]]:
        """Send alert notification to all configured targets.

        Returns dict of target -> (success, error_message).
        """
        message = NotificationMessage(
            title=f"Alert Triggered: {symbol}",
            body=f"Condition: {condition}\nCurrent Price: {price:.2f}",
            severity="alert",
            symbol=symbol,
            price=price,
        )

        results: dict[str, tuple[bool, str]] = {}
        for target in (targets or self.get_active_targets()):
            results[target] = self.send(target, message)
        return results

    def get_active_targets(self) -> list[str]:
        """List all configured notification targets."""
        secrets = read_secrets()
        targets: list[str] = []

        for key in secrets:
            if key.startswith("DISCORD_WEBHOOK_"):
                name = key.replace("DISCORD_WEBHOOK_", "").lower()
                targets.append(f"discord:{name}")
            elif key.startswith("TELEGRAM_BOT_TOKEN_"):
                name = key.replace("TELEGRAM_BOT_TOKEN_", "").lower()
                # Only add if chat_id also exists
                if secrets.get(f"TELEGRAM_CHAT_ID_{name.upper()}"):
                    targets.append(f"telegram:{name}")

        return targets

    def test_notification(self, target: str) -> tuple[bool, str]:
        """Send a test notification to verify webhook configuration.

        Returns (success, error_message).
        """
        message = NotificationMessage(
            title="Test Notification",
            body="FinCLI webhook test successful! ✅",
            severity="info",
        )
        return self.send(target, message)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def configure_discord_webhook(name: str, webhook_url: str) -> None:
    """Save Discord webhook URL to secrets."""
    save_secret(f"DISCORD_WEBHOOK_{name.upper()}", webhook_url)


def configure_telegram_webhook(name: str, bot_token: str, chat_id: str) -> None:
    """Save Telegram bot token and chat ID to secrets."""
    save_secret(f"TELEGRAM_BOT_TOKEN_{name.upper()}", bot_token)
    save_secret(f"TELEGRAM_CHAT_ID_{name.upper()}", chat_id)


def remove_webhook(target: str) -> bool:
    """Remove a webhook configuration."""
    parts = target.split(":", 1)
    if len(parts) != 2:
        return False

    webhook_type, name = parts[0].lower(), parts[1]

    if webhook_type == "discord":
        save_secret(f"DISCORD_WEBHOOK_{name.upper()}", "")
        return True
    if webhook_type == "telegram":
        save_secret(f"TELEGRAM_BOT_TOKEN_{name.upper()}", "")
        save_secret(f"TELEGRAM_CHAT_ID_{name.upper()}", "")
        return True
    return False
