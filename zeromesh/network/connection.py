"""
ZeroMesh Network — Async TCP Connection
========================================
Wraps asyncio StreamReader/StreamWriter with the ZeroMesh framing protocol.

Each PeerConnection manages a single full-duplex TCP connection.
It provides:
  - send(msg)          → encode and write a message to the wire
  - receive()          → read and decode the next message from the wire
  - close()            → graceful shutdown with GOODBYE
  - RTT measurement    → ping() returns measured round-trip time in ms
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from zeromesh.network.protocol import (
    HEADER_SIZE,
    Message,
    MessageType,
    decode_body,
    decode_header,
    encode_message,
)


# ─── Peer Identity ────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PeerAddress:
    """Network address of a peer node."""
    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


# ─── Connection ───────────────────────────────────────────────────────────────

class PeerConnection:
    """
    Full-duplex async TCP connection to a single peer.

    Usage (client side)::

        conn = await PeerConnection.connect(PeerAddress("127.0.0.1", 7400))
        await conn.send(Message.ping("my-node-id"))
        reply = await conn.receive()
        await conn.close()

    Usage (server side, from accepted stream)::

        conn = PeerConnection.from_streams(reader, writer, addr)
        msg = await conn.receive()
        await conn.send(Message.pong("my-node-id"))

    Attributes:
        address:     The remote peer's address.
        is_closed:   True after close() has been called.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        address: PeerAddress,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self.address = address
        self.is_closed = False
        self._send_lock = asyncio.Lock()  # serialize concurrent sends

    # ── Factory methods ───────────────────────────────────────────

    @classmethod
    async def connect(
        cls,
        address: PeerAddress,
        timeout: float = 5.0,
    ) -> "PeerConnection":
        """
        Open an outbound TCP connection to ``address``.

        Args:
            address: Remote peer's host and port.
            timeout: Connection timeout in seconds.

        Raises:
            ConnectionRefusedError: if nothing is listening.
            asyncio.TimeoutError:   if connection takes longer than ``timeout``.
        """
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address.host, address.port),
            timeout=timeout,
        )
        return cls(reader, writer, address)

    @classmethod
    def from_streams(
        cls,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        address: PeerAddress,
    ) -> "PeerConnection":
        """Wrap already-accepted server streams into a PeerConnection."""
        return cls(reader, writer, address)

    # ── Send ──────────────────────────────────────────────────────

    async def send(self, msg: Message) -> None:
        """
        Encode and write a message to the wire.

        Thread-safe: uses an internal lock so multiple coroutines can
        call send() concurrently without interleaving frames.

        Raises:
            ConnectionError: if the connection is closed.
        """
        if self.is_closed:
            raise ConnectionError(f"Connection to {self.address} is closed")

        frame = encode_message(msg)
        async with self._send_lock:
            self._writer.write(frame)
            await self._writer.drain()

    # ── Receive ───────────────────────────────────────────────────

    async def receive(self, timeout: float = 30.0) -> Message:
        """
        Read and decode exactly one message from the wire.

        Steps:
          1. Read 5-byte header → parse body_len and msg_type.
          2. Read body_len - 1 bytes (payload).
          3. Decode msgpack payload → return Message.

        Args:
            timeout: Max seconds to wait for a complete message.

        Returns:
            The next Message from this peer.

        Raises:
            ConnectionError:    if the peer closed the connection mid-read (EOF).
            asyncio.TimeoutError: if no message arrives within ``timeout``.
            ValueError:         if the frame is malformed or msg type is unknown.
        """
        raw_header = await asyncio.wait_for(
            self._read_exactly(HEADER_SIZE),
            timeout=timeout,
        )
        body_len, msg_type_int = decode_header(raw_header)

        # body_len includes the type byte; payload is (body_len - 1) bytes
        payload_len = body_len - 1
        payload_bytes = b""
        if payload_len > 0:
            payload_bytes = await asyncio.wait_for(
                self._read_exactly(payload_len),
                timeout=timeout,
            )

        return decode_body(payload_bytes, msg_type_int)

    async def _read_exactly(self, n: int) -> bytes:
        """
        Read exactly ``n`` bytes from the stream.

        Raises:
            ConnectionError: on EOF before n bytes are read.
        """
        data = await self._reader.readexactly(n)
        if len(data) < n:
            raise ConnectionError(
                f"Peer {self.address} closed connection mid-frame "
                f"(got {len(data)}/{n} bytes)"
            )
        return data

    # ── RTT Measurement ───────────────────────────────────────────

    async def ping(self, node_id: str, timeout: float = 5.0) -> float:
        """
        Send a PING and measure the round-trip time.

        Args:
            node_id: Our own node ID to include in the PING.
            timeout: Max seconds to wait for PONG.

        Returns:
            RTT in milliseconds.

        Raises:
            asyncio.TimeoutError: if no PONG arrives in time.
            ValueError:           if the response is not a PONG.
        """
        t0 = time.perf_counter()
        await self.send(Message.ping(node_id))
        reply = await self.receive(timeout=timeout)
        rtt_ms = (time.perf_counter() - t0) * 1000

        if reply.type != MessageType.PONG:
            raise ValueError(f"Expected PONG, got {reply.type.name}")

        return rtt_ms

    # ── Lifecycle ─────────────────────────────────────────────────

    async def close(self) -> None:
        """
        Send GOODBYE and close the TCP connection gracefully.
        Safe to call multiple times (idempotent).
        """
        if self.is_closed:
            return
        self.is_closed = True
        try:
            await self.send(Message.goodbye())
        except Exception:
            pass  # peer may already be gone
        finally:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    def __repr__(self) -> str:
        state = "closed" if self.is_closed else "open"
        return f"PeerConnection({self.address}, {state})"
