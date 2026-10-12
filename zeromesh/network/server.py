"""
ZeroMesh Network — Async TCP Server
=====================================
Listens for inbound peer connections and dispatches each to a handler coroutine.

Usage::

    async def handle(conn: PeerConnection) -> None:
        msg = await conn.receive()
        if msg.type == MessageType.PING:
            await conn.send(Message.pong("my-node-id"))
        await conn.close()

    server = NodeServer(host="0.0.0.0", port=7400, handler=handle)
    await server.start()
    # ... run until shutdown
    await server.stop()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from zeromesh.network.connection import PeerAddress, PeerConnection

logger = logging.getLogger(__name__)

# Type alias: a handler receives a PeerConnection and returns a coroutine
ConnectionHandler = Callable[[PeerConnection], Awaitable[None]]


@dataclass
class NodeServer:
    """
    Async TCP server that accepts inbound peer connections.

    Each accepted connection is wrapped in a PeerConnection and dispatched
    to the user-supplied ``handler`` coroutine in its own asyncio Task.
    If the handler raises, the exception is logged and the connection is closed.

    Attributes:
        host:     Bind address (e.g., "0.0.0.0" or "127.0.0.1").
        port:     TCP port to listen on.
        handler:  Coroutine called for each accepted connection.
        backlog:  Max number of pending connections in the OS queue.
    """

    host: str
    port: int
    handler: ConnectionHandler
    backlog: int = 100

    _server: asyncio.Server | None = field(default=None, init=False, repr=False)
    _tasks: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    @property
    def address(self) -> PeerAddress:
        return PeerAddress(self.host, self.port)

    async def start(self) -> None:
        """
        Bind the socket and start accepting connections.

        Raises:
            OSError: if the port is already in use.
        """
        self._server = await asyncio.start_server(
            self._accept,
            host=self.host,
            port=self.port,
            backlog=self.backlog,
            reuse_address=True,
        )
        logger.info("NodeServer listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """
        Stop accepting new connections and wait for active handlers to finish.
        """
        if self._server is None:
            return

        self._server.close()
        await self._server.wait_closed()
        logger.info("NodeServer on :%d stopped", self.port)

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    # ── Internal ──────────────────────────────────────────────────

    async def _accept(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Called by asyncio for every new inbound connection."""
        peername = writer.get_extra_info("peername")
        remote_host, remote_port = peername[0], peername[1]
        peer_addr = PeerAddress(remote_host, remote_port)

        conn = PeerConnection.from_streams(reader, writer, peer_addr)
        logger.debug("Accepted connection from %s", peer_addr)

        task = asyncio.create_task(self._run_handler(conn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_handler(self, conn: PeerConnection) -> None:
        """Wrap the user handler with error handling and guaranteed close."""
        try:
            await self.handler(conn)
        except asyncio.IncompleteReadError:
            logger.debug("Peer %s disconnected mid-stream", conn.address)
        except Exception as exc:
            logger.warning("Handler error for %s: %r", conn.address, exc)
        finally:
            if not conn.is_closed:
                await conn.close()
