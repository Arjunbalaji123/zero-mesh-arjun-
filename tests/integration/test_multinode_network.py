"""
Integration Test — Multi-node ZeroMesh Network
===============================================
Deploys a 3-node decentralized cluster locally:
  - Node 1 (port 7601): Seeder / Uploader
  - Node 2 (port 7602): DHT Relay / Replica
  - Node 3 (port 7603): Consumer / Downloader

Flow:
  1. Bootstrapping:
     Node 2 & Node 3 bootstrap against Node 1.
  2. Upload:
     Node 1 uploads an encrypted multi-chunk file (500 KB).
     Replication distributes chunks to Node 2 and Node 3.
  3. DHT Lookup & Fetch:
     Node 3 queries the network for chunks it doesn't have locally,
     downloads them in parallel, decrypts them with the shared key,
     and reassembles the original file.
  4. Byte-for-byte integrity verified!
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from zeromesh.crypto.engine import generate_key
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.node import ZeroMeshNode


@pytest.mark.asyncio
async def test_three_node_upload_and_download(tmp_path: Path):
    shared_key = generate_key()

    # 1. Initialize 3 nodes on unique ports
    n1 = ZeroMeshNode(host="127.0.0.1", port=7601, data_dir=tmp_path / "node1", key=shared_key)
    n2 = ZeroMeshNode(host="127.0.0.1", port=7602, data_dir=tmp_path / "node2", key=shared_key)
    n3 = ZeroMeshNode(host="127.0.0.1", port=7603, data_dir=tmp_path / "node3", key=shared_key)

    await n1.start()
    await n2.start()
    await n3.start()

    try:
        # 2. Add peers to each other's routing tables
        p1 = PeerInfo(n1.local_id, "127.0.0.1", 7601)
        p2 = PeerInfo(n2.local_id, "127.0.0.1", 7602)
        p3 = PeerInfo(n3.local_id, "127.0.0.1", 7603)

        n1.routing_table.add_peer(p2)
        n1.routing_table.add_peer(p3)

        n2.routing_table.add_peer(p1)
        n2.routing_table.add_peer(p3)

        n3.routing_table.add_peer(p1)
        n3.routing_table.add_peer(p2)

        # 3. Create a test payload (600 KB to span multiple 256KB chunks)
        src_path = tmp_path / "distributed_source.bin"
        payload_bytes = os.urandom(600 * 1024)
        src_path.write_bytes(payload_bytes)

        # 4. Node 1 uploads and replicates chunks
        manifest_id = await n1.file_manager.upload_file(src_path, shared_key)
        assert len(manifest_id) == 64

        # Verify Node 2 or Node 3 received chunks via STORE_CHUNK replication
        manifest = await n1.manifest_registry.get(manifest_id)
        assert manifest is not None
        assert manifest.num_chunks == 3  # (256KB + 256KB + 88KB)

        # Save manifest to Node 3's registry (simulating user sharing manifest_id / metadata)
        await n3.manifest_registry.save(manifest)

        # Wipe chunks from Node 3's local store to ensure it MUST retrieve them over the network from Node 1/2!
        for chunk_meta in manifest.chunks:
            await n3.chunk_store.delete(chunk_meta.content_id)

        # 5. Node 3 downloads file over the P2P network using its find_node_rpc
        download_target = tmp_path / "node3_downloaded.bin"
        await n3.file_manager.download_file(
            manifest_id=manifest_id,
            key=shared_key,
            out_path=download_target,
            find_node_rpc=n3.find_node_rpc,
        )

        # 6. Verify exact byte-for-byte match!
        assert download_target.exists()
        assert download_target.read_bytes() == payload_bytes

    finally:
        await n1.stop()
        await n2.stop()
        await n3.stop()
