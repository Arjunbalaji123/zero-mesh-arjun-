"""
ZeroMesh DHT — Routing Table
==============================

The routing table is an array of 256 K-Buckets, one per bit of the key space.

Bucket assignment
-----------------
When a peer with ID ``p`` is seen by our node with ID ``n``:

    bucket_index = (n.distance(p)).bucket_index()
                 = most-significant-bit position of (n XOR p)

This means:
  - Bucket 255: peers that differ from us only in the LSB  (closest)
  - Bucket 0:   peers that differ from us in the MSB       (farthest)

We maintain MANY buckets for the close range (where we know lots of nodes)
and FEW entries for the distant range (where we know almost nobody).
This produces the logarithmic routing table size O(log n).

FIND_NODE closest-k query
--------------------------
``closest_peers(target, count=k)`` returns the ``count`` peers in the
routing table sorted by XOR distance to ``target``.  This is the core
primitive used by the iterative lookup algorithm.
"""

from __future__ import annotations

from zeromesh.dht.kbucket import K, KBucket, PeerInfo
from zeromesh.dht.node_id import NodeID

# Number of buckets = ID_BITS (one per bit of the 256-bit key space)
NUM_BUCKETS = 256


class RoutingTable:
    """
    Full 256-bucket Kademlia routing table for a single local node.

    Attributes:
        local_id: This node's own NodeID — used to compute XOR distances.
        k:        Max peers per bucket (default 20).
    """

    def __init__(self, local_id: NodeID, k: int = K) -> None:
        self.local_id = local_id
        self.k = k
        self._buckets: list[KBucket] = [KBucket(k=k) for _ in range(NUM_BUCKETS)]

    # ── Insertion / Update ────────────────────────────────────────

    def add_or_update(self, peer: PeerInfo) -> bool:
        """
        Insert or refresh a peer in the appropriate k-bucket.

        Args:
            peer: The peer to add.

        Returns:
            True  — peer was added/updated.
            False — bucket was full (caller should handle LRS ping).

        Raises:
            ValueError: if ``peer.node_id == self.local_id``.
        """
        if peer.node_id == self.local_id:
            raise ValueError("Cannot add local node to its own routing table")

        idx = self._bucket_index_for(peer.node_id)
        return self._buckets[idx].add_or_update(peer)

    def add_peer(self, peer: PeerInfo) -> bool:
        """Alias for add_or_update."""
        return self.add_or_update(peer)

    def mark_seen(self, node_id: NodeID) -> None:
        """Promote a peer to MRS position after any successful contact."""
        if node_id == self.local_id:
            return
        idx = self._bucket_index_for(node_id)
        self._buckets[idx].mark_seen(node_id)

    def remove(self, node_id: NodeID) -> bool:
        """Remove a confirmed-dead peer from the routing table."""
        if node_id == self.local_id:
            return False
        idx = self._bucket_index_for(node_id)
        return self._buckets[idx].remove(node_id)

    def evict_lrs(self, node_id: NodeID) -> PeerInfo | None:
        """
        Evict the LRS peer from the bucket that would hold ``node_id``
        and promote from its replacement cache.

        Returns the evicted peer (so the caller can mark it dead).
        """
        idx = self._bucket_index_for(node_id)
        return self._buckets[idx].evict_lrs_and_promote()

    # ── Queries ───────────────────────────────────────────────────

    def contains(self, node_id: NodeID) -> bool:
        """True if the node is currently in the routing table."""
        if node_id == self.local_id:
            return False
        idx = self._bucket_index_for(node_id)
        return self._buckets[idx].contains(node_id)

    def closest_peers(self, target: NodeID, count: int | None = None) -> list[PeerInfo]:
        """
        Return up to ``count`` peers closest to ``target`` by XOR distance.

        This is the response to a FIND_NODE RPC:
          - Collect all known peers from all non-empty buckets.
          - Sort by XOR distance to ``target``.
          - Return the closest ``count`` (default: self.k).

        O(n log n) where n is total peers known — acceptable because
        routing tables stay small (O(log N) total peers).
        """
        count = count or self.k
        all_peers = self.all_peers()
        return sorted(all_peers, key=lambda p: target.distance(p.node_id).value)[:count]

    def all_peers(self) -> list[PeerInfo]:
        """Flat list of every peer in the routing table."""
        result: list[PeerInfo] = []
        for bucket in self._buckets:
            result.extend(bucket.peers)
        return result

    def bucket_for(self, node_id: NodeID) -> KBucket:
        """Return the KBucket responsible for ``node_id``."""
        return self._buckets[self._bucket_index_for(node_id)]

    @property
    def total_peers(self) -> int:
        """Total number of peers currently tracked."""
        return sum(len(b) for b in self._buckets)

    @property
    def non_empty_buckets(self) -> int:
        """Number of buckets that contain at least one peer."""
        return sum(1 for b in self._buckets if len(b) > 0)

    # ── Internals ─────────────────────────────────────────────────

    def _bucket_index_for(self, node_id: NodeID) -> int:
        """
        Compute which bucket index to use for ``node_id``.

        bucket_index = (self.local_id XOR node_id).bit_length() - 1
                     = most significant bit position of XOR distance

        Edge case: if XOR distance is 0 (self == node_id) this would return
        -1, but we reject self-insertion above, so bucket index is always
        0–255.
        """
        dist = self.local_id.distance(node_id)
        idx = dist.bucket_index()
        # Clamp to valid range [0, NUM_BUCKETS-1]
        return max(0, min(idx, NUM_BUCKETS - 1))

    def __repr__(self) -> str:
        return (
            f"RoutingTable(local={self.local_id!r}, "
            f"peers={self.total_peers}, "
            f"buckets={self.non_empty_buckets}/{NUM_BUCKETS})"
        )
