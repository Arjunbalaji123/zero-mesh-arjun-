"""
ZeroMesh DHT — Node Identity & XOR Distance Metric
====================================================

Every node and every stored chunk is identified by a 256-bit ID drawn
from the same flat key space.

Node IDs
--------
A node's ID is the SHA-256 of its canonical address string "host:port".
This gives us a deterministic, collision-resistant assignment that distributes
nodes uniformly across the 2^256 key space without a central authority.

XOR Metric
----------
Kademlia uses bitwise XOR as its distance function:

    distance(a, b) = a XOR b

Why XOR and not absolute difference?

1. **Symmetry**: d(a,b) = d(b,a)               — so A knows B is close iff B knows A is close.
2. **Triangle inequality**: d(a,c) ≤ d(a,b) XOR d(b,c)  — needed for routing correctness.
3. **Unidirectionality**: for any point a and distance d, there is exactly
   ONE point b such that d(a,b) = d.  This means lookups converge: each
   hop halves the distance remaining.

Bucket index
------------
The index of the k-bucket responsible for a peer is the position of the
**most significant bit** of the XOR distance (counting from bit 255 down to 0).

    bucket_index = 255 - leading_zeros(a XOR b)

    Example (8-bit analogy):
        a = 0b10110011
        b = 0b10100101
        a XOR b = 0b00010110  →  leading zeros = 3  →  bucket = 4
"""

from __future__ import annotations

import hashlib
import secrets


# ─── Constants ────────────────────────────────────────────────────────────────

ID_BITS  = 256          # 256-bit key space (SHA-256 output)
ID_BYTES = ID_BITS // 8  # 32 bytes


# ─── NodeID ───────────────────────────────────────────────────────────────────

class NodeID:
    """
    An immutable 256-bit Kademlia node or chunk identifier.

    Internally stored as a ``bytes`` object of length 32.
    Supports comparison, hashing (usable as dict key), and XOR distance.

    Construction:

        NodeID.from_address("127.0.0.1", 7400)   # deterministic from host:port
        NodeID.from_hex("deadbeef...")            # from 64-char hex string
        NodeID.from_bytes(b"...")                  # from 32-byte buffer
        NodeID.random()                            # random (for testing)
        NodeID.from_content_id("sha256hex...")    # chunk content addressing
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes) -> None:
        if len(raw) != ID_BYTES:
            raise ValueError(f"NodeID must be {ID_BYTES} bytes, got {len(raw)}")
        self._raw = raw

    # ── Factories ─────────────────────────────────────────────────

    @classmethod
    def from_address(cls, host: str, port: int) -> "NodeID":
        """Deterministic ID from a node's network address."""
        canonical = f"{host}:{port}".encode()
        return cls(hashlib.sha256(canonical).digest())

    @classmethod
    def from_hex(cls, hex_str: str) -> "NodeID":
        """Parse a 64-character hex string."""
        raw = bytes.fromhex(hex_str)
        return cls(raw)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NodeID":
        return cls(data)

    @classmethod
    def from_content_id(cls, content_id_hex: str) -> "NodeID":
        """
        Map a chunk's SHA-256 content ID into the DHT key space.
        Since content IDs are already SHA-256 hex digests, this is a direct
        conversion — the chunk's DHT key IS its content hash.
        """
        return cls.from_hex(content_id_hex)

    @classmethod
    def random(cls) -> "NodeID":
        """Generate a random 256-bit ID (useful for testing / bootstrap)."""
        return cls(secrets.token_bytes(ID_BYTES))

    # ── Properties ────────────────────────────────────────────────

    @property
    def hex(self) -> str:
        """Lowercase hex representation (64 chars)."""
        return self._raw.hex()

    @property
    def as_int(self) -> int:
        """Integer representation (big-endian)."""
        return int.from_bytes(self._raw, "big")

    # ── XOR Distance ──────────────────────────────────────────────

    def distance(self, other: "NodeID") -> "XORDistance":
        """
        Compute the XOR distance between this node and ``other``.

        Returns an XORDistance object that carries the raw integer distance
        and exposes helper methods like ``bucket_index()``.
        """
        xor_int = self.as_int ^ other.as_int
        return XORDistance(xor_int)

    def bucket_index(self, other: "NodeID") -> int:
        """
        Which k-bucket index should ``other`` be placed in,
        from *this* node's perspective?

        Returns 0–255 (255 = closest bucket, 0 = farthest).
        Returns -1 if other == self (same node, not stored in any bucket).
        """
        return self.distance(other).bucket_index()

    # ── Ordering & Hashing ────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if isinstance(other, NodeID):
            return self._raw == other._raw
        return NotImplemented

    def __lt__(self, other: "NodeID") -> bool:
        return self._raw < other._raw

    def __hash__(self) -> int:
        return hash(self._raw)

    def __repr__(self) -> str:
        return f"NodeID({self.hex[:16]}...)"

    def __bytes__(self) -> bytes:
        return self._raw


# ─── XOR Distance ─────────────────────────────────────────────────────────────

class XORDistance:
    """
    The XOR distance between two NodeIDs.

    Wraps the raw integer result of ``a.as_int XOR b.as_int`` and
    provides routing-relevant derived quantities.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int) -> None:
        self._value = value

    @property
    def value(self) -> int:
        """Raw integer XOR distance."""
        return self._value

    def bucket_index(self) -> int:
        """
        Position of the most significant set bit (0-indexed from LSB).

        This is the k-bucket index from the perspective of the local node:
        - Distance 0 (self) → returns -1 (no bucket for self)
        - Very close peers → small bucket index
        - Very far peers  → bucket index close to 255

        The index equals ``ID_BITS - 1 - leading_zeros``.
        """
        if self._value == 0:
            return -1  # same node
        return self._value.bit_length() - 1

    def __lt__(self, other: "XORDistance") -> bool:
        return self._value < other._value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, XORDistance):
            return self._value == other._value
        return NotImplemented

    def __repr__(self) -> str:
        return f"XORDistance(bucket={self.bucket_index()}, val={self._value:#066x})"
