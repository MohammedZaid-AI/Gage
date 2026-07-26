"""In-process WebSocket broadcast hub for live dashboard updates."""
import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("gage.realtime")


class Broadcaster:
    """Tracks connected dashboards and pushes JSON events to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("dashboard connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("dashboard disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Send {event, data} to every client, dropping dead sockets."""
        payload = {"event": event, "data": data}
        async with self._lock:
            targets = list(self._clients)
        logger.info("dashboard updated: broadcast %r -> %d client(s)", event, len(targets))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # client vanished mid-send
                await self.disconnect(ws)


broadcaster = Broadcaster()
