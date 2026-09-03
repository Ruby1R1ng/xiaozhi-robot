"""Bridge a remote WebSocket endpoint to a local stdio MCP server."""

import asyncio
import logging
import os
import random
import signal
import subprocess
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

from config_manager import load_config


load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("MCP_PIPE")

INITIAL_BACKOFF = 1
MAX_BACKOFF = 600
reconnect_attempt = 0
backoff = INITIAL_BACKOFF
mcp_script = ""


async def connect_with_retry(uri: str) -> None:
    global reconnect_attempt, backoff
    while True:
        try:
            if reconnect_attempt > 0:
                wait_time = backoff * (1 + random.random() * 0.1)
                logger.info(
                    "Waiting %.2f seconds before reconnection attempt %d",
                    wait_time,
                    reconnect_attempt,
                )
                await asyncio.sleep(wait_time)
            await connect_to_server(uri)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reconnect_attempt += 1
            logger.warning(
                "Connection closed (attempt %d, error %s)",
                reconnect_attempt,
                type(exc).__name__,
            )
            backoff = min(backoff * 2, MAX_BACKOFF)


async def connect_to_server(uri: str) -> None:
    global reconnect_attempt, backoff
    process: subprocess.Popen[str] | None = None
    try:
        logger.info("Connecting to configured WebSocket endpoint")
        async with websockets.connect(
            uri,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        ) as websocket:
            logger.info("Successfully connected to WebSocket endpoint")
            reconnect_attempt = 0
            backoff = INITIAL_BACKOFF

            process = subprocess.Popen(
                [sys.executable, mcp_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
            )
            logger.info("Started MCP process")

            tasks = {
                asyncio.create_task(pipe_websocket_to_process(websocket, process)),
                asyncio.create_task(pipe_process_to_websocket(process, websocket)),
                asyncio.create_task(pipe_process_stderr_to_terminal(process)),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception:
                    raise exception
            raise RuntimeError("A bridge task ended unexpectedly")
    finally:
        if process is not None and process.poll() is None:
            logger.info("Terminating MCP process")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


async def pipe_websocket_to_process(websocket, process: subprocess.Popen[str]) -> None:
    if process.stdin is None:
        raise RuntimeError("MCP process stdin is unavailable")
    try:
        while True:
            message = await websocket.recv()
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            process.stdin.write(message + "\n")
            process.stdin.flush()
    finally:
        if not process.stdin.closed:
            process.stdin.close()


async def pipe_process_to_websocket(process: subprocess.Popen[str], websocket) -> None:
    if process.stdout is None:
        raise RuntimeError("MCP process stdout is unavailable")
    while True:
        data = await asyncio.get_running_loop().run_in_executor(None, process.stdout.readline)
        if not data:
            raise RuntimeError("MCP process stdout closed")
        await websocket.send(data)


async def pipe_process_stderr_to_terminal(process: subprocess.Popen[str]) -> None:
    if process.stderr is None:
        raise RuntimeError("MCP process stderr is unavailable")
    while True:
        data = await asyncio.get_running_loop().run_in_executor(None, process.stderr.readline)
        if not data:
            raise RuntimeError("MCP process stderr closed")
        sys.stderr.write(data)
        sys.stderr.flush()


def signal_handler(signum, _frame) -> None:
    logger.info("Received signal %d, shutting down", signum)
    raise KeyboardInterrupt


def main() -> None:
    global mcp_script
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if len(sys.argv) != 2:
        raise SystemExit("Usage: mcp_pipe.py <mcp_script>")

    script_path = Path(sys.argv[1]).resolve()
    if not script_path.is_file():
        raise SystemExit(f"MCP script does not exist: {script_path}")
    mcp_script = str(script_path)

    endpoint_url = os.getenv("MCP_ENDPOINT", "").strip()
    if not endpoint_url:
        endpoint_url = str(load_config().get("MCP_ENDPOINT", "")).strip()
    if not endpoint_url.startswith(("ws://", "wss://")) or "token=..." in endpoint_url:
        raise SystemExit("MCP_ENDPOINT is missing or invalid")

    try:
        asyncio.run(connect_with_retry(endpoint_url))
    except KeyboardInterrupt:
        logger.info("Service stopped")


if __name__ == "__main__":
    main()
