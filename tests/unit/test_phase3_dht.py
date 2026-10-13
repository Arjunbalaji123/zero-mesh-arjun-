"""
Unit tests — Phase 3: Kademlia DHT
  - NodeID & XOR distance
  - K-Bucket (insertion, eviction, replacement cache)
  - RoutingTable (bucket assignment, closest-k query)
  - KademliaLookup (iterative FIND_NODE with fake in-memory network)
"""

from __future__ import annotations

import pytest

from zeromesh.dht.kbucket import KBucket, PeerInfo
from zeromesh.dht.lookup import KademliaLookup
from zeromesh.dht.node_id import ID_BYTES, NodeID
from zeromesh.dht.routing_table import RoutingTable

# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_id(hex_prefix: str, fill: str = "0") -> NodeID:
    """Create a NodeID from a short hex prefix padded to 64 chars."""
    padded = (hex_prefix + fill * 64)[:64]
    return NodeID.from_hex(padded)


def make_peer(hex_prefix: str, fill: str = "0", port: int = 7000) -> PeerInfo:
    return PeerInfo(node_id=make_id(hex_prefix, fill), host="127.0.0.1", port=port)


# ══════════════════════════════════════════════════════════════════════════════
# NodeID & XOR Distance
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeID:
    def test_from_hex_roundtrip(self):
        nid = NodeID.random()
        assert NodeID.from_hex(nid.hex) == nid

    def test_from_bytes_roundtrip(self):
        nid = NodeID.random()
        assert NodeID.from_bytes(bytes(nid)) == nid

    def test_from_address_deterministic(self):
        a = NodeID.from_address("127.0.0.1", 7400)
        b = NodeID.from_address("127.0.0.1", 7400)
        assert a == b

    def test_from_address_different_ports(self):
        a = NodeID.from_address("127.0.0.1", 7400)
        b = NodeID.from_address("127.0.0.1", 7401)
        assert a != b

    def test_random_unique(self):
        ids = {NodeID.random() for _ in range(100)}
        assert len(ids) == 100

    def test_length(self):
        nid = NodeID.random()
        assert len(bytes(nid)) == ID_BYTES

    def test_hex_length(self):
        assert len(NodeID.random().hex) == 64

    def test_equality(self):
        a = make_id("ab")
        b = make_id("ab")
        assert a == b

    def test_inequality(self):
        assert make_id("ab") != make_id("cd")

    def test_hashable_as_dict_key(self):
        d = {NodeID.random(): "value"}
        assert len(d) == 1

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError):
            NodeID(b"\x00" * 10)

    def test_from_content_id(self):
        # A content ID is a 64-char SHA-256 hex — should map cleanly to NodeID
        from zeromesh.crypto import sha256_hash
        cid = sha256_hash(b"test chunk data")
        nid = NodeID.from_content_id(cid)
        assert nid.hex == cid


class TestXORDistance:
    def test_self_distance_zero(self):
        nid = NodeID.random()
        dist = nid.distance(nid)
        assert dist.value == 0
        assert dist.bucket_index() == -1

    def test_symmetric(self):
        a, b = NodeID.random(), NodeID.random()
        assert a.distance(b).value == b.distance(a).value

    def test_triangle_inequality(self):
        a, b, c = NodeID.random(), NodeID.random(), NodeID.random()
        d_ab = a.distance(b).value
        d_bc = b.distance(c).value
        d_ac = a.distance(c).value
        # XOR triangle inequality: d(a,c) <= d(a,b) XOR d(b,c)
        # (This is actually d(a,c) <= max(d(a,b), d(b,c)) which is stricter)
        assert d_ac <= (d_ab ^ d_bc) or d_ac <= max(d_ab, d_bc)

    def test_bucket_index_range(self):
        a, b = NodeID.random(), NodeID.random()
        idx = a.bucket_index(b)
        assert 0 <= idx <= 255

    def test_known_bucket_index(self):
        # a = 0x80...0  (MSB set)
        # b = 0x00...0  (all zeros)
        # XOR = 0x80...0 → MSB is bit 255 → bucket_index = 255
        a = NodeID.from_hex("80" + "00" * 31)
        b = NodeID.from_hex("00" * 32)
        assert a.bucket_index(b) == 255

    def test_close_nodes_small_bucket_index(self):
        # Differ only in the last byte → XOR < 256 → bit_length <= 8 → bucket < 8
        a = NodeID.from_hex("00" * 31 + "01")
        b = NodeID.from_hex("00" * 31 + "02")
        assert a.bucket_index(b) <= 7

    def test_xor_distance_ordering(self):
        # Three nodes: a, b, c where b is closer to a than c
        a = NodeID.from_hex("00" * 32)
        b = NodeID.from_hex("00" * 31 + "01")   # distance 1
        c = NodeID.from_hex("ff" + "00" * 31)   # distance very large
        assert a.distance(b) < a.distance(c)


# ══════════════════════════════════════════════════════════════════════════════
# K-Bucket
# ══════════════════════════════════════════════════════════════════════════════

class TestKBucket:
    def _bucket(self, k: int = 3) -> KBucket:
        return KBucket(k=k)

    def test_add_peer(self):
        b = self._bucket()
        p = make_peer("aa")
        assert b.add_or_update(p) is True
        assert b.contains(p.node_id)
        assert len(b) == 1

    def test_update_moves_to_mrs(self):
        b = self._bucket(k=3)
        p1, p2, p3 = make_peer("01"), make_peer("02"), make_peer("03")
        b.add_or_update(p1)
        b.add_or_update(p2)
        b.add_or_update(p3)
        # p1 is LRS; re-add p1 → should become MRS
        b.add_or_update(p1)
        assert b.mrs == p1
        assert b.lrs == p2

    def test_full_bucket_returns_false(self):
        b = self._bucket(k=2)
        b.add_or_update(make_peer("01"))
        b.add_or_update(make_peer("02"))
        result = b.add_or_update(make_peer("03"))
        assert result is False

    def test_full_bucket_goes_to_replacement_cache(self):
        b = self._bucket(k=2)
        b.add_or_update(make_peer("01"))
        b.add_or_update(make_peer("02"))
        b.add_or_update(make_peer("03"))  # goes to cache
        assert len(b) == 2   # still only 2 in main bucket
        assert len(b._replacement_cache) == 1

    def test_evict_lrs_promotes_from_cache(self):
        b = self._bucket(k=2)
        p1, p2, p3 = make_peer("01"), make_peer("02"), make_peer("03")
        b.add_or_update(p1)
        b.add_or_update(p2)
        b.add_or_update(p3)  # → replacement cache
        evicted = b.evict_lrs_and_promote()
        assert evicted == p1         # LRS was p1
        assert b.contains(p3.node_id)  # p3 promoted
        assert len(b) == 2

    def test_remove_peer(self):
        b = self._bucket(k=3)
        p = make_peer("aa")
        b.add_or_update(p)
        assert b.remove(p.node_id) is True
        assert not b.contains(p.node_id)

    def test_remove_nonexistent(self):
        b = self._bucket()
        assert b.remove(make_id("ff")) is False

    def test_mark_seen(self):
        b = self._bucket(k=3)
        p1, p2 = make_peer("01"), make_peer("02")
        b.add_or_update(p1)
        b.add_or_update(p2)
        b.mark_seen(p1.node_id)
        assert b.mrs == p1
        assert b.lrs == p2

    def test_is_full(self):
        b = self._bucket(k=2)
        b.add_or_update(make_peer("01"))
        b.add_or_update(make_peer("02"))
        assert b.is_full

    def test_peers_snapshot(self):
        b = self._bucket(k=5)
        peers = [make_peer(f"0{i}") for i in range(3)]
        for p in peers:
            b.add_or_update(p)
        snapshot = b.peers
        assert len(snapshot) == 3
        # Mutating snapshot does not affect bucket
        snapshot.clear()
        assert len(b) == 3


# ══════════════════════════════════════════════════════════════════════════════
# Routing Table
# ══════════════════════════════════════════════════════════════════════════════

class TestRoutingTable:
    def _table(self, local_hex: str = "00" * 32) -> RoutingTable:
        return RoutingTable(NodeID.from_hex(local_hex), k=20)

    def test_add_peer(self):
        rt = self._table()
        peer = make_peer("ff")
        rt.add_or_update(peer)
        assert rt.contains(peer.node_id)

    def test_cannot_add_self(self):
        local = NodeID.from_hex("00" * 32)
        rt = RoutingTable(local)
        with pytest.raises(ValueError):
            rt.add_or_update(PeerInfo(local, "127.0.0.1", 7400))

    def test_different_distance_different_buckets(self):
        local = NodeID.from_hex("00" * 32)
        rt = RoutingTable(local, k=20)
        # close peer: XOR distance small → low bucket index
        close = PeerInfo(NodeID.from_hex("00" * 31 + "01"), "127.0.0.1", 1)
        # far peer: XOR distance large → high bucket index
        far   = PeerInfo(NodeID.from_hex("ff" + "00" * 31), "127.0.0.1", 2)
        rt.add_or_update(close)
        rt.add_or_update(far)
        bi_close = rt._bucket_index_for(close.node_id)
        bi_far   = rt._bucket_index_for(far.node_id)
        assert bi_close < bi_far

    def test_total_peers(self):
        rt = self._table()
        for i in range(1, 6):
            rt.add_or_update(PeerInfo(NodeID.random(), "127.0.0.1", i))
        assert rt.total_peers == 5

    def test_closest_peers_sorted(self):
        target = NodeID.from_hex("00" * 32)
        rt = RoutingTable(NodeID.from_hex("aa" * 32), k=20)

        peers = [PeerInfo(NodeID.random(), "127.0.0.1", i) for i in range(10)]
        for p in peers:
            rt.add_or_update(p)

        closest = rt.closest_peers(target, count=5)
        assert len(closest) <= 5

        # Verify sorted order
        distances = [target.distance(p.node_id).value for p in closest]
        assert distances == sorted(distances)

    def test_closest_peers_count_capped(self):
        rt = self._table()
        for i in range(5):
            rt.add_or_update(PeerInfo(NodeID.random(), "127.0.0.1", i))
        result = rt.closest_peers(NodeID.random(), count=20)
        assert len(result) <= 5  # can't return more than we have

    def test_remove_peer(self):
        rt = self._table()
        peer = make_peer("ff")
        rt.add_or_update(peer)
        assert rt.remove(peer.node_id) is True
        assert not rt.contains(peer.node_id)

    def test_mark_seen(self):
        rt = self._table()
        peer = make_peer("ab")
        rt.add_or_update(peer)
        rt.mark_seen(peer.node_id)  # Should not raise
        assert rt.contains(peer.node_id)

    def test_repr(self):
        rt = self._table()
        assert "RoutingTable" in repr(rt)


# ══════════════════════════════════════════════════════════════════════════════
# Kademlia Iterative Lookup
# ══════════════════════════════════════════════════════════════════════════════

class FakeNetwork:
    """
    In-memory fake network for testing KademliaLookup.

    Each "node" has a routing table. A FIND_NODE RPC to a peer returns
    that peer's closest peers to the target.
    """

    def __init__(self) -> None:
        self._tables: dict[NodeID, RoutingTable] = {}

    def add_node(self, node_id: NodeID, peers: list[PeerInfo]) -> None:
        rt = RoutingTable(node_id, k=20)
        for p in peers:
            if p.node_id != node_id:
                try:
                    rt.add_or_update(p)
                except ValueError:
                    pass
        self._tables[node_id] = rt

    def make_rpc(self):
        """Return an async callable matching the FindNodeRPC protocol."""
        tables = self._tables

        async def rpc(peer: PeerInfo, target: NodeID) -> list[PeerInfo]:
            rt = tables.get(peer.node_id)
            if rt is None:
                return []
            return rt.closest_peers(target, count=20)

        return rpc


def build_ring(n: int) -> tuple[FakeNetwork, list[PeerInfo]]:
    """
    Build a fake n-node fully-connected network.
    Returns (network, list_of_all_peers).
    """
    all_peers = [PeerInfo(NodeID.random(), "127.0.0.1", 7000 + i) for i in range(n)]
    net = FakeNetwork()
    for peer in all_peers:
        others = [p for p in all_peers if p.node_id != peer.node_id]
        net.add_node(peer.node_id, others)
    return net, all_peers


class TestKademliaLookup:
    async def test_lookup_finds_target_in_small_network(self):
        """In a 10-node network, we should find the node closest to any target."""
        net, peers = build_ring(10)
        local = peers[0]
        target = NodeID.random()

        lookup = KademliaLookup(
            local_id=local.node_id,
            target=target,
            initial_peers=peers[1:4],  # start with 3 known nodes
            rpc=net.make_rpc(),
            k=20,
            alpha=3,
        )
        result = await lookup.run()
        assert len(result) > 0

        # Result should be sorted by distance to target
        distances = [target.distance(p.node_id).value for p in result]
        assert distances == sorted(distances)

    async def test_lookup_no_initial_peers_returns_empty(self):
        net, peers = build_ring(5)
        lookup = KademliaLookup(
            local_id=peers[0].node_id,
            target=NodeID.random(),
            initial_peers=[],
            rpc=net.make_rpc(),
        )
        result = await lookup.run()
        assert result == []

    async def test_lookup_does_not_include_self(self):
        net, peers = build_ring(10)
        local = peers[0]
        target = NodeID.random()

        lookup = KademliaLookup(
            local_id=local.node_id,
            target=target,
            initial_peers=peers[1:],
            rpc=net.make_rpc(),
        )
        result = await lookup.run()
        node_ids = {p.node_id for p in result}
        assert local.node_id not in node_ids

    async def test_lookup_returns_at_most_k(self):
        net, peers = build_ring(50)
        local = peers[0]
        k = 5
        lookup = KademliaLookup(
            local_id=local.node_id,
            target=NodeID.random(),
            initial_peers=peers[1:4],
            rpc=net.make_rpc(),
            k=k,
        )
        result = await lookup.run()
        assert len(result) <= k

    async def test_lookup_converges_large_network(self):
        """100-node network — lookup should still find close peers."""
        net, peers = build_ring(100)
        local = peers[0]
        target = peers[50].node_id  # look up an actual node

        lookup = KademliaLookup(
            local_id=local.node_id,
            target=target,
            initial_peers=peers[1:4],
            rpc=net.make_rpc(),
            k=20,
            alpha=3,
        )
        result = await lookup.run()
        result_ids = {p.node_id for p in result}
        # The actual target node should be in the result
        assert peers[50].node_id in result_ids

    async def test_lookup_handles_unresponsive_peers(self):
        """Peers that return [] (simulating timeouts) should not break lookup."""
        net, peers = build_ring(20)
        local = peers[0]

        original_rpc = net.make_rpc()
        call_count = [0]

        async def flaky_rpc(peer: PeerInfo, target: NodeID) -> list[PeerInfo]:
            call_count[0] += 1
            # First 3 calls fail (simulate timeout)
            if call_count[0] <= 3:
                return []
            return await original_rpc(peer, target)

        lookup = KademliaLookup(
            local_id=local.node_id,
            target=NodeID.random(),
            initial_peers=peers[1:4],
            rpc=flaky_rpc,
            k=20,
            alpha=3,
        )
        result = await lookup.run()
        # Should still work, just with fewer results
        assert isinstance(result, list)
