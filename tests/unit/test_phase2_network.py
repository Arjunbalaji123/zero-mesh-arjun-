"""
Unit & integration tests — Phase 2: Wire Protocol + Async TCP + Peer Scorer
"""

from __future__ import annotations

import asyncio
import math
import struct

import pytest

from zeromesh.network.connection import PeerAddress, PeerConnection
from zeromesh.network.peer_scorer import PeerScorer, PeerStats
from zeromesh.network.protocol import (
    HEADER_SIZE,
    MAX_FRAME_BYTES,
    Message,
    MessageType,
    decode_body,
    decode_header,
    encode_message,
)
from zeromesh.network.server import NodeServer

# ══════════════════════════════════════════════════════════════════════════════
# Protocol / Framing Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMessageConstructors:
    def test_ping(self):
        m = Message.ping("node-abc")
        assert m.type == MessageType.PING
        assert m.payload["node_id"] == "node-abc"

    def test_pong(self):
        m = Message.pong("node-xyz", rtt_ms=12.5)
        assert m.type == MessageType.PONG
        assert m.payload["rtt_ms"] == pytest.approx(12.5)

    def test_store_chunk(self):
        m = Message.store_chunk("deadbeef", nonce=b"x" * 12, ciphertext=b"y" * 32)
        assert m.type == MessageType.STORE_CHUNK
        assert m.payload["content_id"] == "deadbeef"
        assert m.payload["nonce"] == b"x" * 12

    def test_error(self):
        m = Message.error(404, "chunk not found")
        assert m.payload["reason"] == "chunk not found"

    def test_repr(self):
        m = Message.ping("n1")
        assert "PING" in repr(m)


class TestFrameEncode:
    def test_header_size(self):
        m = Message.ping("test")
        frame = encode_message(m)
        assert len(frame) >= HEADER_SIZE

    def test_header_body_len(self):
        m = Message.goodbye()
        frame = encode_message(m)
        # Header = 4-byte length + 1-byte type = HEADER_SIZE bytes
        # body_len = 1 (type byte) + len(msgpack payload)
        # So: total frame = HEADER_SIZE + (body_len - 1) + ... wait:
        # encode_message writes: header(4B length + ... no:
        # frame = [4B body_len][1B type][payload_bytes]
        # body_len = 1 + len(payload_bytes)
        # total frame length = 4 + 1 + len(payload_bytes) = 4 + body_len
        body_len = struct.unpack("!I", frame[:4])[0]
        assert len(frame) == 4 + body_len

    def test_header_type_byte(self):
        m = Message.ping("n1")
        frame = encode_message(m)
        # Byte 4 is the type
        type_byte = frame[4]
        assert type_byte == MessageType.PING.value

    def test_roundtrip_ping(self):
        m = Message.ping("roundtrip-node")
        frame = encode_message(m)
        body_len, msg_type_int = decode_header(frame[:HEADER_SIZE])
        payload_bytes = frame[HEADER_SIZE: HEADER_SIZE + body_len - 1]
        decoded = decode_body(payload_bytes, msg_type_int)
        assert decoded.type == MessageType.PING
        assert decoded.payload["node_id"] == "roundtrip-node"

    def test_roundtrip_binary_payload(self):
        nonce = bytes(range(12))
        ct = bytes(range(256))
        m = Message.store_chunk("abc123", nonce=nonce, ciphertext=ct)
        frame = encode_message(m)
        body_len, mtype = decode_header(frame[:HEADER_SIZE])
        payload_bytes = frame[HEADER_SIZE: HEADER_SIZE + body_len - 1]
        decoded = decode_body(payload_bytes, mtype)
        assert decoded.payload["nonce"] == nonce
        assert decoded.payload["ciphertext"] == ct

    def test_oversized_payload_raises(self):
        m = Message(MessageType.STORE_CHUNK, {"data": b"x" * (MAX_FRAME_BYTES + 1)})
        with pytest.raises(ValueError, match="Frame too large"):
            encode_message(m)


class TestFrameDecode:
    def test_wrong_header_size_raises(self):
        with pytest.raises(ValueError, match="Header must be"):
            decode_header(b"\x00" * 3)

    def test_zero_body_len_raises(self):
        # Pack body_len=0, type=0x01
        raw = struct.pack("!IB", 0, 1)
        with pytest.raises(ValueError, match="body_len cannot be 0"):
            decode_header(raw)

    def test_oversized_body_len_raises(self):
        raw = struct.pack("!IB", MAX_FRAME_BYTES + 1, 0x01)
        with pytest.raises(ValueError, match="oversized frame"):
            decode_header(raw)

    def test_unknown_message_type_raises(self):
        with pytest.raises(ValueError, match="Unknown MessageType"):
            decode_body(b"", 0xAB)

    def test_goodbye_empty_payload(self):
        m = Message.goodbye()
        frame = encode_message(m)
        body_len, mtype = decode_header(frame[:HEADER_SIZE])
        payload_bytes = frame[HEADER_SIZE: HEADER_SIZE + body_len - 1]
        decoded = decode_body(payload_bytes, mtype)
        assert decoded.type == MessageType.GOODBYE
        assert decoded.payload == {}


# ══════════════════════════════════════════════════════════════════════════════
# Async TCP — Live Server/Client Integration Tests
# ══════════════════════════════════════════════════════════════════════════════

def find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned port."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestPingPong:
    """Spin up a real server and connect a real client."""

    async def _echo_handler(self, conn: PeerConnection) -> None:
        """Server: reply to PING with PONG, then close."""
        msg = await conn.receive()
        if msg.type == MessageType.PING:
            await conn.send(Message.pong("server-node", rtt_ms=0.0))
        await conn.close()

    async def test_ping_pong_roundtrip(self):
        port = find_free_port()
        server = NodeServer(host="127.0.0.1", port=port, handler=self._echo_handler)
        await server.start()

        try:
            conn = await PeerConnection.connect(PeerAddress("127.0.0.1", port))
            await conn.send(Message.ping("client-node"))
            reply = await conn.receive()
            assert reply.type == MessageType.PONG
            assert reply.payload["node_id"] == "server-node"
            await conn.close()
        finally:
            await server.stop()

    async def test_rtt_measurement(self):
        port = find_free_port()

        async def pong_handler(conn: PeerConnection) -> None:
            msg = await conn.receive()
            if msg.type == MessageType.PING:
                await conn.send(Message.pong("server"))
            await conn.close()

        server = NodeServer("127.0.0.1", port, pong_handler)
        await server.start()

        try:
            conn = await PeerConnection.connect(PeerAddress("127.0.0.1", port))
            rtt = await conn.ping("client")
            assert rtt > 0
            assert rtt < 500  # loopback should be well under 500 ms
        finally:
            await server.stop()

    async def test_multiple_messages_same_connection(self):
        port = find_free_port()
        received: list[Message] = []

        async def multi_handler(conn: PeerConnection) -> None:
            for _ in range(3):
                msg = await conn.receive()
                received.append(msg)
                if msg.type == MessageType.GOODBYE:
                    break
            await conn.close()

        server = NodeServer("127.0.0.1", port, multi_handler)
        await server.start()

        try:
            conn = await PeerConnection.connect(PeerAddress("127.0.0.1", port))
            await conn.send(Message.ping("c"))
            await conn.send(Message.get_chunk("abc123"))
            await conn.send(Message.goodbye())
            await asyncio.sleep(0.05)  # let server process
        finally:
            await server.stop()

        assert received[0].type == MessageType.PING
        assert received[1].type == MessageType.GET_CHUNK
        assert received[2].type == MessageType.GOODBYE

    async def test_chunk_store_and_retrieve(self):
        port = find_free_port()
        stored: dict[str, tuple[bytes, bytes]] = {}

        async def storage_handler(conn: PeerConnection) -> None:
            msg = await conn.receive()
            if msg.type == MessageType.STORE_CHUNK:
                cid = msg.payload["content_id"]
                stored[cid] = (msg.payload["nonce"], msg.payload["ciphertext"])
                await conn.send(Message.store_ack(cid))
            elif msg.type == MessageType.GET_CHUNK:
                cid = msg.payload["content_id"]
                nonce, ct = stored[cid]
                await conn.send(Message.chunk_data(cid, nonce, ct))
            await conn.close()

        # --- STORE ---
        server = NodeServer("127.0.0.1", port, storage_handler)
        await server.start()

        nonce = b"\xAB" * 12
        ct = b"\xCD" * 64
        cid = "test-content-id"

        conn = await PeerConnection.connect(PeerAddress("127.0.0.1", port))
        await conn.send(Message.store_chunk(cid, nonce, ct))
        ack = await conn.receive()
        assert ack.type == MessageType.STORE_ACK
        assert ack.payload["content_id"] == cid
        await conn.close()

        # --- RETRIEVE (new connection) ---
        async def get_handler(conn: PeerConnection) -> None:
            msg = await conn.receive()
            cid_ = msg.payload["content_id"]
            n, c = stored[cid_]
            await conn.send(Message.chunk_data(cid_, n, c))
            await conn.close()

        server2 = NodeServer("127.0.0.1", find_free_port(), get_handler)
        await server2.start()

        conn2 = await PeerConnection.connect(server2.address)
        await conn2.send(Message.get_chunk(cid))
        reply = await conn2.receive()
        assert reply.type == MessageType.CHUNK_DATA
        assert reply.payload["nonce"] == nonce
        assert reply.payload["ciphertext"] == ct
        await conn2.close()

        await server.stop()
        await server2.stop()

    async def test_connection_refused(self):
        with pytest.raises((ConnectionRefusedError, OSError)):
            await PeerConnection.connect(PeerAddress("127.0.0.1", 1), timeout=0.5)

    async def test_closed_connection_send_raises(self):
        port = find_free_port()

        async def noop(conn: PeerConnection) -> None:
            await conn.close()

        server = NodeServer("127.0.0.1", port, noop)
        await server.start()

        try:
            conn = await PeerConnection.connect(PeerAddress("127.0.0.1", port))
            conn.is_closed = True
            with pytest.raises(ConnectionError):
                await conn.send(Message.ping("n"))
        finally:
            await server.stop()


# ══════════════════════════════════════════════════════════════════════════════
# Peer Scorer Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPeerScorer:
    def test_unknown_peer_neutral_score(self):
        scorer = PeerScorer()
        assert scorer.score("unknown") == pytest.approx(0.5)

    def test_success_increases_score(self):
        scorer = PeerScorer()
        baseline = scorer.score("p1")
        for _ in range(10):
            scorer.record_success("p1", rtt_ms=10.0)
        assert scorer.score("p1") > baseline

    def test_failure_decreases_score(self):
        scorer = PeerScorer()
        # Prime with some successes
        for _ in range(5):
            scorer.record_success("p1", rtt_ms=10.0)
        good_score = scorer.score("p1")
        # Now add many failures
        for _ in range(10):
            scorer.record_failure("p1")
        assert scorer.score("p1") < good_score

    def test_high_rtt_lower_score_than_low_rtt(self):
        scorer = PeerScorer()
        scorer.record_success("fast", rtt_ms=5.0)
        scorer.record_success("slow", rtt_ms=1500.0)
        assert scorer.score("fast") > scorer.score("slow")

    def test_rank_peers_best_first(self):
        scorer = PeerScorer()
        scorer.record_success("p1", rtt_ms=10.0)
        scorer.record_success("p2", rtt_ms=800.0)
        scorer.record_failure("p2")
        scorer.record_failure("p2")

        ranked = scorer.rank_peers(["p2", "p1"])
        assert ranked[0] == "p1"

    def test_evict_candidate_worst_peer(self):
        scorer = PeerScorer()
        scorer.record_success("good", rtt_ms=5.0)
        for _ in range(5):
            scorer.record_failure("bad")

        victim = scorer.evict_candidate(["good", "bad"])
        assert victim == "bad"

    def test_consecutive_failures_exponential_penalty(self):
        scorer = PeerScorer()
        scorer.record_success("p1", rtt_ms=10.0)
        scorer.record_failure("p1")
        s1 = scorer.score("p1")
        scorer.record_failure("p1")
        s2 = scorer.score("p1")
        scorer.record_failure("p1")
        s3 = scorer.score("p1")
        # Each extra consecutive failure should drop score further
        assert s1 > s2 > s3

    def test_success_resets_consecutive_failures(self):
        scorer = PeerScorer()
        for _ in range(5):
            scorer.record_failure("p1")
        bad_score = scorer.score("p1")
        scorer.record_success("p1", rtt_ms=20.0)
        stats = scorer.get("p1")
        assert stats.consecutive_failures == 0
        assert scorer.score("p1") > bad_score

    def test_score_bounded_01(self):
        scorer = PeerScorer()
        for _ in range(200):
            scorer.record_success("p1", rtt_ms=1.0)
        s = scorer.score("p1")
        assert 0.0 <= s <= 1.0

    def test_streak_score_formula(self):
        """Verify exponential decay: exp(-0.5 * k) matches implementation."""
        from zeromesh.network.peer_scorer import PeerScorer
        stats = PeerStats(node_id="t")
        stats.consecutive_failures = 4
        score = PeerScorer._streak_score(stats)
        assert score == pytest.approx(math.exp(-0.5 * 4))
