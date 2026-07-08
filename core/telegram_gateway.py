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
import traceback

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
OPERATOR_ID = os.environ.get("TELEGRAM_OPERATOR_CHAT_ID")

if not TOKEN or not OPERATOR_ID:
    log.critical("FATAL: TELEGRAM_BOT_TOKEN and TELEGRAM_OPERATOR_CHAT_ID must be set.")
    sys.exit(1)

try:
    OPERATOR_ID = int(OPERATOR_ID)
except ValueError:
    log.critical("FATAL: TELEGRAM_OPERATOR_CHAT_ID must be an integer.")
    sys.exit(1)

STATE_URL = "http://127.0.0.1:50000/state"
INJECT_URL = "http://127.0.0.1:50000/inject"
NOTIFICATIONS_URL = "http://127.0.0.1:50000/notifications"

# Telegram message length limit
TG_MAX_LENGTH = 4096

# ── Identity Verification Middleware ──────────────────────────────────────────

class OperatorOnlyMiddleware:
    """Silently drop any update not from the verified operator."""
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            if event.from_user and event.from_user.id == OPERATOR_ID:
                return await handler(event, data)
            else:
                log.warning(f"SECURITY: Dropped unauthorized message from UID {event.from_user.id if event.from_user else 'unknown'}.")
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
            log.error(f"> TELEGRAM: Failed to send message chunk ({len(chunk)} chars): {exc}")
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
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(STATE_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    await safe_send(None, f"Failed to fetch state: HTTP {resp.status}", message, is_reply=True)
                    return
                state = await resp.json()
        except Exception as exc:
            log.error(f"> TELEGRAM: Error fetching state: {exc}")
            await safe_send(None, f"Error fetching state: {exc}", message, is_reply=True)
            return

    vram_used = state.get('vram_used_gb', 0.0)
    vram_total = state.get('vram_total_gb', 0.0)
    cpu_load = state.get('cpu_pct', 0.0)
    phase = state.get('phase', 'UNKNOWN')
    iteration = state.get('iteration', 0)
    uptime = state.get('uptime_seconds', 0)
    disk_free = state.get('disk_free_gb', 0.0)
    failures = state.get('consecutive_failures', 0)
    routing = state.get('inference_routing', 'N/A')
    model = state.get('active_model', 'N/A')
    ts = state.get('thought_stream', [])
    last_thought = ts[-1] if ts else "No thoughts yet"
    btrfs_id = state.get('btrfs_snapshot_id', 'N/A')
    btrfs_ts = state.get('btrfs_timestamp', 'N/A')

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
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("http://127.0.0.1:50000/debug", timeout=10) as resp:
                data = await resp.json()
                logs = data.get("logs", "No logs")
                await safe_send(None, f"Debug Logs:\n{logs[-3500:]}", message, is_reply=True)
        except Exception as exc:
            await safe_send(None, f"Error fetching debug logs: {exc}", message, is_reply=True)

@dp.message(Command("task"))
async def cmd_task(message: Message):
    """Package the instruction and POST it to /inject."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_send(None, "Usage: /task <instruction>", message, is_reply=True)
        return
    
    instruction = parts[1]
    log.info(f"> TELEGRAM: Received /task command. Payload length: {len(instruction)}")
    
    payload = {"command": instruction}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(INJECT_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await safe_send(
                        None,
                        f"Task Accepted\n\nInstruction: {instruction}\nStatus: {data.get('status', 'unknown')}\n\nThe task has been injected into the Kriya Loop. You will receive a push notification when it completes.",
                        message,
                        is_reply=True,
                    )
                else:
                    err = await resp.text()
                    await safe_send(None, f"Failed to inject task (HTTP {resp.status}):\n{err}", message, is_reply=True)
        except Exception as exc:
            log.error(f"> TELEGRAM: Error posting task: {exc}")
            await safe_send(None, f"Error posting task: {exc}", message, is_reply=True)


@dp.message(Command("route"))
async def cmd_route(message: Message):
    """Cognitive Routing Mutation"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await safe_send(None, "Usage: /route <tier> <model>\nTiers: traffic_cop, heavy_lifter", message, is_reply=True)
        return
    tier, model = parts[1], parts[2]
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "http://127.0.0.1:50000/api/v1/config/route",
                json={"tier": tier, "model": model},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    await safe_send(None, f"Route mutation successful: {tier} -> {model}", message, is_reply=True)
                else:
                    err = await resp.text()
                    await safe_send(None, f"Route mutation failed (HTTP {resp.status}):\n{err}", message, is_reply=True)
        except Exception as exc:
            await safe_send(None, f"Error mutating route: {exc}", message, is_reply=True)


@dp.message(Command("system"))
async def cmd_system(message: Message):
    """System Directives mapping to Host Executor intents"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_send(None, "Usage: /system <action>", message, is_reply=True)
        return
    action = parts[1].upper()
    
    payload = {"command": f"EXECUTE INTENT: {action}"}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(INJECT_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    await safe_send(None, f"System directive injected: {action}", message, is_reply=True)
                else:
                    err = await resp.text()
                    await safe_send(None, f"Directive injection failed (HTTP {resp.status}):\n{err}", message, is_reply=True)
        except Exception as exc:
            await safe_send(None, f"Error injecting directive: {exc}", message, is_reply=True)


@dp.message(Command("api"))
async def cmd_api(message: Message):
    """API Key Injection via unprivileged C2 gateway to root Host Executor"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await safe_send(None, "Usage: /api <provider> <key>", message, is_reply=True)
        return
    provider, key = parts[1], parts[2]
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "http://127.0.0.1:50000/api/v1/secrets/update",
                json={"provider": provider, "key": key},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    await safe_send(None, f"API Key proxy queued for {provider}", message, is_reply=True)
                else:
                    err = await resp.text()
                    await safe_send(None, f"Failed to proxy API key (HTTP {resp.status}):\n{err}", message, is_reply=True)
        except Exception as exc:
            await safe_send(None, f"Error proxying API key: {exc}", message, is_reply=True)


@dp.message()
async def default_handler(message: Message):
    """Catch-all for unknown commands."""
    await safe_send(
        None,
        "Unknown command. Available commands:\n"
        "- /report\n"
        "- /task <instruction>\n"
        "- /route <tier> <model>\n"
        "- /system <action>\n"
        "- /api <provider> <key>",
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
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # First, retry any previously failed notifications
                if retry_queue:
                    still_failed = []
                    for notif in retry_queue:
                        success = await safe_send(OPERATOR_ID, f"🔔 YantraOS Notification\n\n{notif}", bot)
                        if not success:
                            still_failed.append(notif)
                    retry_queue.clear()
                    # Only keep retrying up to max_retries worth of accumulated failures
                    if len(still_failed) <= max_retries * 10:
                        retry_queue.extend(still_failed)
                    else:
                        log.warning(f"> TELEGRAM: Dropping {len(still_failed)} notifications after repeated failures.")
                
                # Fetch new notifications from the engine
                async with session.get(NOTIFICATIONS_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        notifications = data.get("notifications", [])
                        for notif in notifications:
                            log.info(f"> TELEGRAM: Dispatching Push Notification ({len(notif)} chars)")
                            success = await safe_send(OPERATOR_ID, f"🔔 YantraOS Notification\n\n{notif}", bot)
                            if not success:
                                log.warning(f"> TELEGRAM: Failed to send notification, queuing for retry.")
                                retry_queue.append(notif)
                
                backoff = 3  # reset backoff on successful poll cycle

            except aiohttp.ClientError as e:
                # Network error reaching the engine — not a Telegram problem
                log.warning(f"> TELEGRAM: Engine unreachable ({type(e).__name__}: {e}), backoff {backoff}s")
                backoff = min(backoff * 2, 60)  # exponential backoff, cap at 60s
            except Exception as e:
                log.error(f"> TELEGRAM: Notification loop error: {e}\n{traceback.format_exc()}")
                backoff = min(backoff * 2, 60)
            
            await asyncio.sleep(backoff)


async def main():
    log.info("> TELEGRAM: Starting YantraOS C2 Gateway...")
    bot = Bot(token=TOKEN)
    
    # Start the background notification polling task
    polling_task = asyncio.create_task(poll_notifications(bot))
    
    try:
        while True:
            try:
                await dp.start_polling(bot)
            except Exception as exc:
                log.warning(f"> FLEET: C2 Gateway Partition Detected. Entering degraded backoff. ({exc})")
                await asyncio.sleep(60)
    finally:
        polling_task.cancel()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
