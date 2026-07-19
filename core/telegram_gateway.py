#!/usr/bin/env python3
"""
YantraOS — Telegram C2 Gateway
Target: /opt/yantra/core/telegram_gateway.py

Provides an out-of-band asynchronous C2 interface for YantraOS via Telegram.
"""

import asyncio
import logging
import os
import sys

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

# ── Configuration ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("yantra.telegram")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CONTROL_TOKEN = os.environ.get("YANTRA_CONTROL_TOKEN")
_OPERATOR_ID = os.environ.get("TELEGRAM_OPERATOR_CHAT_ID")


def _positive_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


OPERATOR_ID = _positive_int(_OPERATOR_ID)
PRIVATE_CHAT_ID = OPERATOR_ID


def _validate_configuration() -> None:
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", TOKEN),
            ("TELEGRAM_OPERATOR_CHAT_ID", _OPERATOR_ID),
            ("YANTRA_CONTROL_TOKEN", CONTROL_TOKEN),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")
    if OPERATOR_ID is None:
        raise RuntimeError("Telegram operator ID must be a positive integer")
    if (
        len(CONTROL_TOKEN) < 32
        or CONTROL_TOKEN.startswith("<")
        or not CONTROL_TOKEN.isprintable()
        or any(char.isspace() for char in CONTROL_TOKEN)
    ):
        raise RuntimeError("YANTRA_CONTROL_TOKEN contains invalid header characters")

STATE_URL = "http://127.0.0.1:50000/state"
INJECT_URL = "http://127.0.0.1:50000/inject"
NOTIFICATIONS_URL = "http://127.0.0.1:50000/notifications"

# Telegram message length limit
TG_MAX_LENGTH = 4096
TASK_MAX_LENGTH = 500
MODEL_MAX_LENGTH = 128
THOUGHT_MAX_LENGTH = 1000


def _engine_session():
    if not CONTROL_TOKEN:
        raise RuntimeError("YANTRA_CONTROL_TOKEN is not configured")
    return aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {CONTROL_TOKEN}"}
    )


def _valid_argument(value: str, max_length: int) -> bool:
    return bool(value and len(value) <= max_length and value.isprintable())


def _bounded_text(value, max_length: int) -> str:
    return str(value)[:max_length]

# ── Identity Verification Middleware ──────────────────────────────────────────

class OperatorOnlyMiddleware:
    """Silently drop any update not from the verified operator."""
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            if (
                event.from_user
                and event.from_user.id == OPERATOR_ID
                and event.chat.type == "private"
                and event.chat.id == PRIVATE_CHAT_ID
            ):
                return await handler(event, data)
            log.warning(
                "SECURITY: Dropped unauthorized Telegram message from UID %s.",
                event.from_user.id if event.from_user else "unknown",
            )
            return
        # Silently drop non-message updates
        return


# ── Safe Send Helper ──────────────────────────────────────────────────────────

async def safe_send(target, text: str, bot_or_message=None, is_reply: bool = False):
    """Send a plain-text message to Telegram with automatic chunking and error handling.
    
    NEVER uses parse_mode — all messages are sent as raw text to avoid
    silent aiogram/Telegram MarkdownV2 parsing failures.
    
    If the message exceeds Telegram's 4096 char limit, it is split into chunks.
    
    Args:
        target: Either a chat_id (int) for bot.send_message, or unused if is_reply.
        text: The message text to send.
        bot_or_message: A Bot instance (for push notifications) or a Message instance (for replies).
        is_reply: If True, uses message.answer(). If False, uses bot.send_message().
    
    Returns:
        True if all chunks sent successfully, False otherwise.
    """
    if not text:
        text = "(empty response)"
    for credential in (TOKEN, CONTROL_TOKEN):
        if credential:
            text = text.replace(credential, "[REDACTED]")
    
    # Split into chunks respecting the Telegram limit
    chunks = []
    while text:
        if len(text) <= TG_MAX_LENGTH:
            chunks.append(text)
            break
        # Find a natural break point (newline) near the limit
        split_at = text.rfind('\n', 0, TG_MAX_LENGTH)
        if split_at == -1 or split_at < TG_MAX_LENGTH // 2:
            split_at = TG_MAX_LENGTH
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip('\n')
    
    all_ok = True
    for chunk in chunks:
        try:
            if is_reply:
                await bot_or_message.answer(chunk)
            else:
                await bot_or_message.send_message(target, chunk)
        except Exception as exc:
            log.error(
                "> TELEGRAM: Failed to send message chunk (%s chars, %s)",
                len(chunk),
                type(exc).__name__,
            )
            all_ok = False
    
    return all_ok


# ── Bot Commands ──────────────────────────────────────────────────────────────

dp = Dispatcher()

# Register the middleware for the message handler
dp.message.middleware(OperatorOnlyMiddleware())


@dp.message(Command("report"))
async def cmd_report(message: Message):
    """Fetch the YantraOS state and format it as a plain-text report."""
    log.info("> TELEGRAM: Received /report command")
    async with _engine_session() as session:
        try:
            async with session.get(
                STATE_URL,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    await safe_send(None, f"Failed to fetch state: HTTP {resp.status}", message, is_reply=True)
                    return
                state = await resp.json()
        except Exception as exc:
            log.error("> TELEGRAM: Error fetching state (%s)", type(exc).__name__)
            await safe_send(None, "Error fetching state.", message, is_reply=True)
            return

    vram_used = state.get('vram_used_gb', 0.0)
    vram_total = state.get('vram_total_gb', 0.0)
    cpu_load = state.get('cpu_pct', 0.0)
    phase = _bounded_text(state.get('phase', 'UNKNOWN'), 32)
    iteration = state.get('iteration', 0)
    uptime = state.get('uptime_seconds', 0)
    disk_free = state.get('disk_free_gb', 0.0)
    failures = state.get('consecutive_failures', 0)
    routing = _bounded_text(state.get('inference_routing', 'N/A'), 128)
    model = _bounded_text(state.get('active_model', 'N/A'), MODEL_MAX_LENGTH)
    ts = state.get('thought_stream', [])
    last_thought = _bounded_text(ts[-1], THOUGHT_MAX_LENGTH) if isinstance(ts, list) and ts else "No thoughts yet"
    btrfs_id = _bounded_text(state.get('btrfs_snapshot_id', 'N/A'), 64)
    btrfs_ts = _bounded_text(state.get('btrfs_timestamp', 'N/A'), 64)

    report = (
        f"=== YantraOS Node Report ===\n\n"
        f"Phase: {phase}\n"
        f"Iteration: {iteration}\n"
        f"Uptime: {uptime}s\n"
        f"CPU Load: {cpu_load}%\n"
        f"VRAM: {vram_used}/{vram_total} GB\n"
        f"Disk Free: {disk_free} GB\n"
        f"Model: {model}\n"
        f"Routing: {routing}\n"
        f"Consecutive Failures: {failures}\n"
        f"BTRFS Snapshot: {btrfs_id} ({btrfs_ts})\n\n"
        f"--- Last Thought ---\n{last_thought}"
    )

    await safe_send(None, report, message, is_reply=True)


@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    async with _engine_session() as session:
        try:
            async with session.get(
                "http://127.0.0.1:50000/debug",
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    await safe_send(None, f"Debug API unavailable: HTTP {resp.status}", message, is_reply=True)
                    return
                data = await resp.json()
                
                lines = ["=== YantraOS Debug Diagnostics ===\n"]
                
                # Secrets file
                sf = data.get("secrets_file", "UNKNOWN")
                if isinstance(sf, list):
                    lines.append("Secrets File: FOUND")
                    for entry in sf:
                        lines.append(f"  {entry}")
                else:
                    lines.append(f"Secrets File: {sf}")
                
                lines.append("")
                
                # Env vars
                env = data.get("env_vars", {})
                lines.append("Environment Variables:")
                for k, v in env.items():
                    lines.append(f"  {k}: {v}")
                
                lines.append("")
                
                # Drop-in
                lines.append(f"Systemd Drop-in: {data.get('dropin', 'UNKNOWN')}")
                
                lines.append("")
                
                # Router state
                lines.append(f"Router local_only: {data.get('router_local_only', 'UNKNOWN')}")
                lines.append(f"Router last_tier: {data.get('router_last_tier', 'UNKNOWN')}")
                
                report = "\n".join(lines)
                await safe_send(None, report, message, is_reply=True)
        except Exception:
            await safe_send(None, "Error fetching debug diagnostics.", message, is_reply=True)

@dp.message(Command("task"))
async def cmd_task(message: Message):
    """Package the instruction and POST it to /inject."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await safe_send(None, "Usage: /task <instruction>", message, is_reply=True)
        return

    instruction = parts[1].strip()
    if not _valid_argument(instruction, TASK_MAX_LENGTH):
        await safe_send(
            None,
            f"Task must be 1-{TASK_MAX_LENGTH} printable characters.",
            message,
            is_reply=True,
        )
        return
    log.info(f"> TELEGRAM: Received /task command. Payload length: {len(instruction)}")

    payload = {"command": instruction}

    async with _engine_session() as session:
        try:
            async with session.post(
                INJECT_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
            ) as resp:
                if resp.status == 200:
                    await safe_send(
                        None,
                        "Task accepted. You will receive a notification when it completes.",
                        message,
                        is_reply=True,
                    )
                else:
                    await safe_send(None, f"Failed to inject task: HTTP {resp.status}", message, is_reply=True)
        except Exception as exc:
            log.error("> TELEGRAM: Error posting task (%s)", type(exc).__name__)
            await safe_send(None, "Error posting task.", message, is_reply=True)


@dp.message()
async def default_handler(message: Message):
    """Catch-all for unknown commands."""
    await safe_send(
        None,
        "Unknown command. Available commands:\n"
        "- /report\n"
        "- /debug\n"
        "- /task <instruction>",
        message,
        is_reply=True,
    )


# ── Push Notification Poller ──────────────────────────────────────────────────

async def poll_notifications(bot: Bot):
    """Background task to poll the engine for push notifications.
    
    KEY DESIGN: Notifications are consumed (cleared) from the engine on fetch.
    If the Telegram send fails, we RETRY the queued notifications rather than
    losing them. Failed notifications are retried up to 3 times with backoff.
    """
    log.info("> TELEGRAM: Starting async notification poller...")
    backoff = 3  # base polling interval
    retry_queue: list[str] = []  # notifications that failed to send
    max_retries = 3
    
    async with _engine_session() as session:
        while True:
            try:
                # First, retry any previously failed notifications
                if retry_queue:
                    still_failed = []
                    for notif in retry_queue:
                        success = await safe_send(PRIVATE_CHAT_ID, f"🔔 YantraOS Notification\n\n{notif}", bot)
                        if not success:
                            still_failed.append(notif)
                    retry_queue.clear()
                    # Only keep retrying up to max_retries worth of accumulated failures
                    if len(still_failed) <= max_retries * 10:
                        retry_queue.extend(still_failed)
                    else:
                        log.warning(f"> TELEGRAM: Dropping {len(still_failed)} notifications after repeated failures.")
                
                # Fetch new notifications from the engine
                async with session.post(
                    NOTIFICATIONS_URL,
                    timeout=aiohttp.ClientTimeout(total=5),
                    allow_redirects=False,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        notifications = data.get("notifications", [])
                        if not isinstance(notifications, list):
                            notifications = []
                        for raw_notification in notifications[:10]:
                            notif = _bounded_text(raw_notification, TG_MAX_LENGTH)
                            log.info(f"> TELEGRAM: Dispatching Push Notification ({len(notif)} chars)")
                            success = await safe_send(PRIVATE_CHAT_ID, f"🔔 YantraOS Notification\n\n{notif}", bot)
                            if not success:
                                log.warning(f"> TELEGRAM: Failed to send notification, queuing for retry.")
                                retry_queue.append(notif)
                
                backoff = 3  # reset backoff on successful poll cycle

            except aiohttp.ClientError as e:
                # Network error reaching the engine — not a Telegram problem
                log.warning(f"> TELEGRAM: Engine unreachable ({type(e).__name__}), backoff {backoff}s")
                backoff = min(backoff * 2, 60)  # exponential backoff, cap at 60s
            except Exception as e:
                log.error(f"> TELEGRAM: Notification loop error ({type(e).__name__})")
                backoff = min(backoff * 2, 60)
            
            await asyncio.sleep(backoff)


async def main():
    _validate_configuration()
    log.info("> TELEGRAM: Starting YantraOS C2 Gateway...")
    bot = Bot(token=TOKEN)
    
    # Start the background notification polling task
    polling_task = asyncio.create_task(poll_notifications(bot))
    
    try:
        while True:
            try:
                await dp.start_polling(bot)
            except Exception as exc:
                log.warning(
                    "> FLEET: C2 Gateway partition detected (%s); entering degraded backoff.",
                    type(exc).__name__,
                )
                await asyncio.sleep(60)
    finally:
        polling_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
