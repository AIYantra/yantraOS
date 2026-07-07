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
from aiogram.utils.markdown import hbold, hcode

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

# ── Identity Verification Middleware ──────────────────────────────────────────

class OperatorOnlyMiddleware:
    """Silently drop any update not from the verified operator."""
    async def __call__(self, handler, event, data):
        # Allow only messages
        if isinstance(event, types.Update) and event.message:
            msg = event.message
            if msg.from_user and msg.from_user.id == OPERATOR_ID:
                return await handler(event, data)
            else:
                log.warning(f"SECURITY: Dropped unauthorized message from UID {msg.from_user.id if msg.from_user else 'unknown'}.")
                return
        elif isinstance(event, types.Message):
            if event.from_user and event.from_user.id == OPERATOR_ID:
                return await handler(event, data)
            else:
                log.warning(f"SECURITY: Dropped unauthorized message from UID {event.from_user.id if event.from_user else 'unknown'}.")
                return
        # Silently drop other updates for now
        return

# ── Bot Commands ──────────────────────────────────────────────────────────────

dp = Dispatcher()

# Register the middleware for the message handler
dp.message.middleware(OperatorOnlyMiddleware())


def escape_code(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`")

def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 format."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)


@dp.message(Command("report"))
async def cmd_report(message: Message):
    """Fetch the YantraOS state and format it as a report."""
    log.info("> TELEGRAM: Received /report command")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(STATE_URL, timeout=10) as resp:
                if resp.status != 200:
                    await message.answer(f"Failed to fetch state: HTTP {resp.status}")
                    return
                state = await resp.json()
        except Exception as exc:
            log.error(f"> TELEGRAM: Error fetching state: {exc}")
            await message.answer(f"Error fetching state: {exc}")
            return

    vram_used = state.get('vram_used_gb', 0.0)
    vram_total = state.get('vram_total_gb', 0.0)
    cpu_load = state.get('cpu_pct', 0.0)
    phase = state.get('phase', 'UNKNOWN')
    
    # We will use consecutive_failures and thought_stream for last action results
    failures = state.get('consecutive_failures', 0)
    ts = state.get('thought_stream', [])
    last_thought = ts[-1] if ts else "No thoughts yet"
    
    # BTRFS Telemetry added here
    btrfs_id = state.get('btrfs_snapshot_id', 'N/A')
    btrfs_ts = state.get('btrfs_timestamp', 'N/A')

    report = (
        f"*YantraOS Node Report*\n\n"
        f"• *Phase*: {escape_md(str(phase))}\n"
        f"• *CPU Load*: {escape_md(str(cpu_load))}%\n"
        f"• *VRAM Usage*: {escape_md(f'{vram_used} / {vram_total} GB')}\n"
        f"• *Consecutive Failures*: {escape_md(str(failures))}\n"
        f"• *BTRFS Checkpoint*: {escape_md(str(btrfs_id))} \\({escape_md(str(btrfs_ts))}\\)\n\n"
        f"*Last Thought*:\n`{escape_code(str(last_thought))}`"
    )

    await message.answer(report, parse_mode="MarkdownV2")


@dp.message(Command("task"))
async def cmd_task(message: Message):
    """Package the instruction and POST it to /inject."""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /task <instruction>")
        return
    
    instruction = parts[1]
    log.info(f"> TELEGRAM: Received /task command. Payload length: {len(instruction)}")
    
    # Send both command/instruction for compatibility with existing parser, 
    # and action/payload to fulfill specific user requirement.
    payload = {
        "command": instruction,
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(INJECT_URL, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await message.answer(f"✅ *Task Accepted*\n\n`{escape_code(str(data))}`", parse_mode="MarkdownV2")
                else:
                    err = await resp.text()
                    await message.answer(f"❌ *Failed to inject task* \\(HTTP {resp.status}\\):\n`{escape_code(err)}`", parse_mode="MarkdownV2")
        except Exception as exc:
            log.error(f"> TELEGRAM: Error posting task: {exc}")
            await message.answer(f"❌ *Error posting task*:\n`{escape_code(str(exc))}`", parse_mode="MarkdownV2")


@dp.message(Command("route"))
async def cmd_route(message: Message):
    """Cognitive Routing Mutation"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: /route <tier> <model>\nTiers: traffic_cop, heavy_lifter")
        return
    tier, model = parts[1], parts[2]
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("http://127.0.0.1:50000/api/v1/config/route", json={"tier": tier, "model": model}, timeout=10) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ Route mutation successful: {tier} -> {model}")
                else:
                    err = await resp.text()
                    await message.answer(f"❌ Route mutation failed \\(HTTP {resp.status}\\):\n`{escape_code(err)}`", parse_mode="MarkdownV2")
        except Exception as exc:
            await message.answer(f"❌ Error mutating route:\n`{escape_code(str(exc))}`", parse_mode="MarkdownV2")


@dp.message(Command("system"))
async def cmd_system(message: Message):
    """System Directives mapping to Host Executor intents"""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /system <action>")
        return
    action = parts[1].upper()
    
    payload = {
        "command": f"EXECUTE INTENT: {action}"
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(INJECT_URL, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ System directive injected: {action}")
                else:
                    err = await resp.text()
                    await message.answer(f"❌ Directive injection failed \\(HTTP {resp.status}\\):\n`{escape_code(err)}`", parse_mode="MarkdownV2")
        except Exception as exc:
            await message.answer(f"❌ Error injecting directive:\n`{escape_code(str(exc))}`", parse_mode="MarkdownV2")


@dp.message(Command("api"))
async def cmd_api(message: Message):
    """API Key Injection via unprivileged C2 gateway to root Host Executor"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Usage: /api <provider> <key>")
        return
    provider, key = parts[1], parts[2]
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post("http://127.0.0.1:50000/api/v1/secrets/update", json={"provider": provider, "key": key}, timeout=10) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ API Key proxy queued for {provider}")
                else:
                    err = await resp.text()
                    await message.answer(f"❌ Failed to proxy API key \\(HTTP {resp.status}\\):\n`{escape_code(err)}`", parse_mode="MarkdownV2")
        except Exception as exc:
            await message.answer(f"❌ Error proxying API key:\n`{escape_code(str(exc))}`", parse_mode="MarkdownV2")


@dp.message()
async def default_handler(message: Message):
    """Catch-all for unknown commands."""
    await message.answer(
        "Unknown command. Available commands:\n"
        "- /report\n"
        "- /task <instruction>\n"
        "- /route <tier> <model>\n"
        "- /system <action>\n"
        "- /api <provider> <key>"
    )


async def poll_notifications(bot: Bot):
    """Background task to continuously poll the engine for push notifications."""
    log.info("> TELEGRAM: Starting async notification poller...")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get("http://127.0.0.1:50000/notifications", timeout=2) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        notifications = data.get("notifications", [])
                        for notif in notifications:
                            log.info(f"> TELEGRAM: Dispatching Push Notification: {notif}")
                            await bot.send_message(OPERATOR_ID, f"🔔 *YantraOS Notification*\n\n`{escape_code(notif)}`", parse_mode="MarkdownV2")
            except Exception:
                pass  # Daemon might be offline or restarting
            await asyncio.sleep(3)


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
