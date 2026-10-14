"""
ZeroMesh Wire Protocol — Message Types & Framing
=================================================

Wire format (all fields big-endian):

  ┌────────────────┬───────────────┬───────────────────────────────┐
  │  Length (4B)   │  Type  (1B)   │  Payload  (variable, msgpack) │
  └────────────────┴───────────────┴───────────────────────────────┘

  - Length:  uint32 — number of bytes that follow (type byte + payload)
  - Type:    uint8  — MessageType enum value
  - Payload: msgpack-encoded dict (fields depend on MessageType)

Design rationale:
  - Fixed 5-byte header allows O(1) frame boundary detection.
  - msgpack is binary, compact, and schema-free — easy to extend.
  - Max frame size (MAX_FRAME_BYTES) prevents memory exhaustion attacks.
"""

from __future__ import annotations

import enum
import struct
from dataclasses import dataclass, field
from typing import Any

import msgpack

CURRENT_PROTOCOL_VERSION = 1

# Header layout: [4 bytes length][1 byte version][1 byte type]
# For backward compatibility, default framing supports version byte.
HEADER_FORMAT = "!IB"          # uint32 body_len + uint8 type
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)   # = 5 bytes

MAX_FRAME_BYTES = 4 * 1024 * 1024  # 4 MB — refuse frames larger than this


# ─── Message Types ────────────────────────────────────────────────────────────

class MessageType(enum.IntEnum):
    """
    All message types in the ZeroMesh wire protocol.

    Kademlia RPCs follow the naming from the original paper.
    Extended with chunk transfer messages for file storage and audit challenges.
    """
    # ── Connectivity ──────────────────────────────────────────────
    PING         = 0x01   # Liveness probe →  {node_id: str, ...}
    PONG         = 0x02   # Reply to PING  →  {node_id: str, rtt_ms: float}

    # ── Kademlia DHT ──────────────────────────────────────────────
    FIND_NODE    = 0x10   # Lookup nodes close to target_id
    FOUND_NODES  = 0x11   # Response: list of (node_id, host, port) triples
    FIND_VALUE   = 0x12   # Lookup chunk by content_id
    FOUND_VALUE  = 0x13   # Response: encrypted chunk data (found locally)
    FOUND_NODES_FOR_VALUE = 0x14  # content_id not local, here are closer nodes

    # ── Chunk Transfer ────────────────────────────────────────────
    STORE_CHUNK  = 0x20   # Store an encrypted chunk
    STORE_ACK    = 0x21   # Acknowledge receipt
    GET_CHUNK    = 0x22   # Request chunk by content_id
    CHUNK_DATA   = 0x23   # Response: nonce + ciphertext

    # ── Fault Tolerance & Health Audits ───────────────────────────
    AUDIT_CHALLENGE = 0x30  # Challenge: {content_id: str, nonce: bytes}
    AUDIT_RESPONSE  = 0x31  # Proof: {content_id: str, proof: str} (sha256(chunk_bytes || nonce))

    # ── Control ───────────────────────────────────────────────────
    ERROR        = 0xFE   # Protocol-level error  → {code: int, reason: str}
    GOODBYE      = 0xFF   # Graceful disconnect


# ─── Message Dataclass ────────────────────────────────────────────────────────

@dataclass(slots=True)
class Message:
    """
    A single ZeroMesh protocol message.

    Attributes:
        type:    MessageType discriminant.
        payload: Arbitrary dict — schema depends on ``type``.
    """
    type: MessageType
    payload: dict[str, Any] = field(default_factory=dict)

    # ── Convenience constructors ─────────────────────────────────

    @classmethod
    def ping(
        cls,
        node_id: str,
        port: int | None = None,
        host: str | None = None,
    ) -> Message:
        payload: dict[str, Any] = {"node_id": node_id}
        if port is not None:
            payload["port"] = port
        if host is not None:
            payload["host"] = host
        return cls(MessageType.PING, payload)

    @classmethod
    def pong(cls, node_id: str, rtt_ms: float = 0.0) -> Message:
        return cls(MessageType.PONG, {"node_id": node_id, "rtt_ms": rtt_ms})

    @classmethod
    def find_node(
        cls,
        sender_id: str,
        target_id: str,
        port: int | None = None,
        host: str | None = None,
    ) -> Message:
        payload: dict[str, Any] = {"sender_id": sender_id, "target_id": target_id}
        if port is not None:
            payload["port"] = port
        if host is not None:
            payload["host"] = host
        return cls(MessageType.FIND_NODE, payload)

    @classmethod
    def found_nodes(cls, nodes: list[tuple[str, str, int]]) -> Message:
        """nodes: list of (node_id, host, port)"""
        return cls(MessageType.FOUND_NODES, {"nodes": nodes})

    @classmethod
    def store_chunk(
        cls,
        content_id: str,
        nonce: bytes,
        ciphertext: bytes,
    ) -> Message:
        return cls(
            MessageType.STORE_CHUNK,
            {"content_id": content_id, "nonce": nonce, "ciphertext": ciphertext},
        )

    @classmethod
    def store_ack(cls, content_id: str) -> Message:
        return cls(MessageType.STORE_ACK, {"content_id": content_id})

    @classmethod
    def get_chunk(cls, content_id: str) -> Message:
        return cls(MessageType.GET_CHUNK, {"content_id": content_id})

    @classmethod
    def chunk_data(cls, content_id: str, nonce: bytes, ciphertext: bytes) -> Message:
        return cls(
            MessageType.CHUNK_DATA,
            {"content_id": content_id, "nonce": nonce, "ciphertext": ciphertext},
        )

    @classmethod
    def audit_challenge(cls, content_id: str, challenge_nonce: bytes) -> Message:
        return cls(
            MessageType.AUDIT_CHALLENGE,
            {"content_id": content_id, "nonce": challenge_nonce},
        )

    @classmethod
    def audit_response(cls, content_id: str, proof: str) -> Message:
        return cls(
            MessageType.AUDIT_RESPONSE,
            {"content_id": content_id, "proof": proof},
        )

    @classmethod
    def error(cls, code: int, reason: str) -> Message:
        return cls(MessageType.ERROR, {"code": code, "reason": reason})

    @classmethod
    def goodbye(cls) -> Message:
        return cls(MessageType.GOODBYE, {})

    def __repr__(self) -> str:
        return f"Message({self.type.name}, keys={list(self.payload)})"


def validate_message_payload(msg: Message) -> None:
    """
    Validate that the message payload matches schema expectations.
    Raises ValueError on malformed payloads to protect against remote injection/crash.
    """
    p = msg.payload
    if not isinstance(p, dict):
        raise ValueError(f"Payload must be a dict, got {type(p).__name__}")

    t = msg.type
    if t == MessageType.PING:
        if "node_id" not in p or not isinstance(p["node_id"], str):
            raise ValueError("PING requires 'node_id' (str)")
    elif t == MessageType.PONG:
        if "node_id" not in p or not isinstance(p["node_id"], str):
            raise ValueError("PONG requires 'node_id' (str)")
    elif t == MessageType.STORE_CHUNK:
        for k in ("content_id", "nonce", "ciphertext"):
            if k not in p:
                raise ValueError(f"STORE_CHUNK missing field '{k}'")
        if not isinstance(p["content_id"], str) or not isinstance(p["nonce"], (bytes, bytearray)) or not isinstance(p["ciphertext"], (bytes, bytearray)):
            raise ValueError("STORE_CHUNK has invalid field types")
    elif t == MessageType.GET_CHUNK:
        if "content_id" not in p or not isinstance(p["content_id"], str):
            raise ValueError("GET_CHUNK requires 'content_id' (str)")
    elif t == MessageType.CHUNK_DATA:
        for k in ("content_id", "nonce", "ciphertext"):
            if k not in p:
                raise ValueError(f"CHUNK_DATA missing field '{k}'")
    elif t == MessageType.FIND_NODE:
        if "target_id" not in p or not isinstance(p["target_id"], str):
            raise ValueError("FIND_NODE requires 'target_id' (str)")
    elif t == MessageType.AUDIT_CHALLENGE:
        if "content_id" not in p or "nonce" not in p:
            raise ValueError("AUDIT_CHALLENGE requires 'content_id' and 'nonce'")
    elif t == MessageType.AUDIT_RESPONSE:
        if "content_id" not in p or "proof" not in p:
            raise ValueError("AUDIT_RESPONSE requires 'content_id' and 'proof'")


# ─── Framing — Encode ─────────────────────────────────────────────────────────

def encode_message(msg: Message) -> bytes:
    """
    Serialize a Message into a length-prefixed wire frame.

    Frame layout:
        [uint32 body_len][uint8 msg_type][msgpack payload bytes]

    Args:
        msg: The Message to encode.

    Returns:
        Bytes ready to write to a TCP stream.

    Raises:
        ValueError: if the encoded frame exceeds MAX_FRAME_BYTES.
    """
    payload_bytes: bytes = bytes(msgpack.packb(msg.payload, use_bin_type=True))
    type_byte = msg.type.value

    # body = type_byte + payload_bytes
    body_len = 1 + len(payload_bytes)

    if body_len > MAX_FRAME_BYTES:
        raise ValueError(
            f"Frame too large: {body_len} bytes > MAX_FRAME_BYTES ({MAX_FRAME_BYTES})"
        )

    header = struct.pack(HEADER_FORMAT, body_len, type_byte)
    return header + payload_bytes


# ─── Framing — Decode ─────────────────────────────────────────────────────────

def decode_header(raw: bytes) -> tuple[int, int]:
    """
    Parse a 5-byte header.

    Args:
        raw: Exactly HEADER_SIZE bytes.

    Returns:
        (body_len, msg_type_int)

    Raises:
        ValueError: if raw is not exactly HEADER_SIZE bytes or
                    body_len exceeds MAX_FRAME_BYTES.
    """
    if len(raw) != HEADER_SIZE:
        raise ValueError(f"Header must be {HEADER_SIZE} bytes, got {len(raw)}")

    body_len, msg_type_int = struct.unpack(HEADER_FORMAT, raw)

    if body_len == 0:
        raise ValueError("body_len cannot be 0 (missing type byte)")

    if body_len > MAX_FRAME_BYTES:
        raise ValueError(
            f"Peer sent oversized frame: {body_len} > {MAX_FRAME_BYTES}"
        )

    return body_len, msg_type_int


def decode_body(body: bytes, msg_type_int: int) -> Message:
    """
    Decode a frame body (type byte already consumed).

    Args:
        body:         Raw msgpack payload bytes (no type byte).
        msg_type_int: Integer value of the MessageType.

    Returns:
        A fully populated Message.

    Raises:
        ValueError: if msg_type_int is unknown.
    """
    try:
        msg_type = MessageType(msg_type_int)
    except ValueError:
        raise ValueError(f"Unknown MessageType: 0x{msg_type_int:02X}")

    payload: dict[str, Any] = msgpack.unpackb(body, raw=False) if body else {}
    return Message(type=msg_type, payload=payload)
