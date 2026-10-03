"""In-process WebSocket broadcast hub for live dashboard updates.

Every socket belongs to one authenticated farmer, and every event is addressed
to the farmer who owns the farm it concerns, so one farmer never receives
another's observations, alerts or node status.
"""
import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("gage.realtime")


class Broadcaster:
    """Tracks connected dashboards per farmer and pushes JSON events to them."""

    def __init__(self) -> None:
        self._clients: dict[WebSocket, int] = {}  # socket -> farmer id
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, farmer_id: int) -> None:
        """Register an already-accepted socket for `farmer_id`."""
        async with self._lock:
            self._clients[ws] = farmer_id
        logger.info("dashboard connected for farmer %d (%d total)", farmer_id, len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(ws, None)
        logger.info("dashboard disconnected (%d total)", len(self._clients))

    async def broadcast(self, event: str, data: dict[str, Any], farmer_id: int) -> None:
        """Send {event, data} to `farmer_id`'s sockets only, dropping dead ones."""
        payload = {"event": event, "data": data}
        async with self._lock:
            targets = [ws for ws, fid in self._clients.items() if fid == farmer_id]
        logger.info("dashboard updated: broadcast %r -> %d client(s)", event, len(targets))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # client vanished mid-send
                await self.disconnect(ws)


broadcaster = Broadcaster()
