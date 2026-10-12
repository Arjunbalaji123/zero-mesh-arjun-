"""
Unit tests — Phase 5: ZeroMeshNode Integration
  - Node lifecycle (start / stop)
  - Inter-node TCP PING / PONG RPC
  - Inter-node DHT FIND_NODE RPC
  - Inter-node STORE_CHUNK / GET_CHUNK RPC
  - Bootstrap discovery
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from zeromesh.crypto.engine import generate_key
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.dht.node_id import NodeID
from zeromesh.network.connection import PeerAddress, PeerConnection
from zeromesh.network.protocol import Message, MessageType
from zeromesh.node import ZeroMeshNode


@pytest.mark.asyncio
class TestZeroMeshNodeIntegration:
    async def test_node_start_stop(self, tmp_path: Path):
        node = ZeroMeshNode(
            host="127.0.0.1",
            port=7501,
            data_dir=tmp_path / "n1",
        )
        assert not node.is_running
        await node.start()
        assert node.is_running
        assert node.server.is_running

        await node.stop()
        assert not node.is_running
        assert not node.server.is_running

    async def test_ping_pong_between_nodes(self, tmp_path: Path):
        node1 = ZeroMeshNode(host="127.0.0.1", port=7502, data_dir=tmp_path / "n1")
        node2 = ZeroMeshNode(host="127.0.0.1", port=7503, data_dir=tmp_path / "n2")

        await node1.start()
        await node2.start()

        try:
            rtt = await node1.ping_peer("127.0.0.1", 7503)
            assert rtt is not None
            assert rtt >= 0.0

            # Node1 should now have Node2 in its routing table
            assert node1.routing_table.total_peers == 1
            peer2 = node1.routing_table.closest_peers(node2.local_id, count=1)[0]
            assert peer2.node_id == node2.local_id
            assert peer2.port == 7503
        finally:
            await node1.stop()
            await node2.stop()

    async def test_find_node_rpc(self, tmp_path: Path):
        node1 = ZeroMeshNode(host="127.0.0.1", port=7504, data_dir=tmp_path / "n1")
        node2 = ZeroMeshNode(host="127.0.0.1", port=7505, data_dir=tmp_path / "n2")
        node3 = ZeroMeshNode(host="127.0.0.1", port=7506, data_dir=tmp_path / "n3")

        await node1.start()
        await node2.start()
        await node3.start()

        try:
            # Tell node2 about node3
            node2.routing_table.add_peer(
                PeerInfo(node_id=node3.local_id, host="127.0.0.1", port=7506)
            )

            # Node1 asks node2 for nodes close to node3
            results = await node1.find_node_rpc(
                PeerInfo(node_id=node2.local_id, host="127.0.0.1", port=7505),
                target=node3.local_id,
            )

            assert len(results) >= 1
            found_ids = {p.node_id.hex for p in results}
            assert node3.local_id.hex in found_ids
        finally:
            await node1.stop()
            await node2.stop()
            await node3.stop()

    async def test_store_and_get_chunk_rpc(self, tmp_path: Path):
        node = ZeroMeshNode(host="127.0.0.1", port=7507, data_dir=tmp_path / "n1")
        await node.start()

        try:
            conn = await PeerConnection.connect(PeerAddress("127.0.0.1", 7507))
            cid = "deadbeef" * 8
            nonce = os.urandom(12)
            ciphertext = b"test encrypted payload"

            # 1. STORE_CHUNK
            await conn.send(Message.store_chunk(cid, nonce, ciphertext))
            ack = await conn.receive(timeout=3.0)
            assert ack.type == MessageType.STORE_ACK
            assert ack.payload["content_id"] == cid

            # Verify saved locally on node
            assert await node.chunk_store.has(cid) is True

            # 2. GET_CHUNK
            await conn.send(Message.get_chunk(cid))
            reply = await conn.receive(timeout=3.0)
            assert reply.type == MessageType.CHUNK_DATA
            assert reply.payload["content_id"] == cid
            assert reply.payload["nonce"] == nonce
            assert reply.payload["ciphertext"] == ciphertext

            # 3. GET_CHUNK for nonexistent ID
            await conn.send(Message.get_chunk("nonexistent" * 4))
            err_reply = await conn.receive(timeout=3.0)
            assert err_reply.type == MessageType.ERROR

            await conn.close()
        finally:
            await node.stop()

    async def test_bootstrap(self, tmp_path: Path):
        seed = ZeroMeshNode(host="127.0.0.1", port=7508, data_dir=tmp_path / "seed")
        newbie = ZeroMeshNode(host="127.0.0.1", port=7509, data_dir=tmp_path / "newbie")

        await seed.start()
        await newbie.start()

        try:
            count = await newbie.bootstrap([("127.0.0.1", 7508)])
            assert count == 1
            assert newbie.routing_table.total_peers >= 1
        finally:
            await seed.stop()
            await newbie.stop()
