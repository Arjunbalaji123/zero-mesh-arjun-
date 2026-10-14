"""
Unit tests — Phase 6: FastAPI REST API & Endpoints
  - POST /api/files/upload
  - GET  /api/files/{manifest_id}
  - GET  /api/files
  - DELETE /api/files/{manifest_id}
  - GET  /api/peers
  - GET  /api/health
  - GET  /metrics
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from zeromesh.api.app import create_app
from zeromesh.dht.kbucket import PeerInfo
from zeromesh.dht.node_id import NodeID
from zeromesh.node import ZeroMeshNode


@pytest.fixture
async def running_node(tmp_path: Path):
    node = ZeroMeshNode(host="127.0.0.1", port=0, data_dir=tmp_path / "node_api")
    await node.start()
    try:
        yield node
    finally:
        await node.stop()


@pytest.fixture
def app(running_node: ZeroMeshNode):
    return create_app(running_node)


@pytest.mark.asyncio
class TestZeroMeshAPI:
    async def test_health_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "node_id" in data
            assert data["port"] > 0
            assert data["stored_chunks"] == 0

    async def test_upload_and_download_file(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            test_content = b"Hello, ZeroMesh decentralized world! Multi-chunk test content." * 50
            files = {"file": ("test.txt", io.BytesIO(test_content), "text/plain")}

            # 1. Upload
            upload_resp = await client.post("/api/files/upload", files=files)
            assert upload_resp.status_code == 200
            upload_data = upload_resp.json()
            assert "manifest_id" in upload_data
            assert upload_data["filename"] == "test.txt"
            manifest_id = upload_data["manifest_id"]

            # 2. List files
            list_resp = await client.get("/api/files")
            assert list_resp.status_code == 200
            file_entries = list_resp.json()
            assert any(f["manifest_id"] == manifest_id for f in file_entries)

            # 3. Download
            dl_resp = await client.get(f"/api/files/{manifest_id}")
            assert dl_resp.status_code == 200
            assert dl_resp.content == test_content
            assert 'filename="test.txt"' in dl_resp.headers["Content-Disposition"]

            # 4. Delete manifest
            del_resp = await client.delete(f"/api/files/{manifest_id}")
            assert del_resp.status_code == 200

            # 5. Download after delete should return 404
            dl_missing = await client.get(f"/api/files/{manifest_id}")
            assert dl_missing.status_code == 404

    async def test_peers_endpoint(self, app, running_node: ZeroMeshNode):
        peer = PeerInfo(node_id=NodeID.random(), host="192.168.1.50", port=7400)
        running_node.routing_table.add_peer(peer)
        running_node.scorer.record_success(peer.node_id.hex, rtt_ms=12.5)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/peers")
            assert resp.status_code == 200
            peers = resp.json()
            assert len(peers) == 1
            assert peers[0]["host"] == "192.168.1.50"
            assert peers[0]["port"] == 7400
            assert peers[0]["score"] > 0.5

    async def test_prometheus_metrics_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics")
            assert resp.status_code == 200
            body = resp.text
            assert "zeromesh_uploads_total" in body
            assert "zeromesh_active_peers" in body

    async def test_dashboard_endpoint(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "ZeroMesh" in resp.text
            assert "DECENTRALIZED ENCRYPTED STORAGE" in resp.text

