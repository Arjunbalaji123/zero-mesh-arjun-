"""
ZeroMesh REST API — FastAPI Application
=========================================
Endpoints:

  POST /api/files/upload              Upload a file → returns manifest_id
  GET  /api/files/{manifest_id}       Download a file
  GET  /api/files                     List uploaded files
  DELETE /api/files/{manifest_id}     Remove a manifest

  GET  /api/peers                     List known peers with scores
  GET  /api/health                    Node health summary
  GET  /metrics                       Prometheus metrics (text/plain)
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from zeromesh.monitoring.metrics import METRICS


# ─── App factory ──────────────────────────────────────────────────────────────

def create_app(node: "ZeroMeshNode") -> FastAPI:  # type: ignore[name-defined]  # noqa: F821
    """
    Build the FastAPI application bound to a live node instance.

    Args:
        node: A fully-initialised ZeroMeshNode (see zeromesh/node.py).

    Returns:
        A FastAPI ASGI application.
    """
    app = FastAPI(
        title="ZeroMesh API",
        description="Decentralized P2P Encrypted File System",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request/Response models ───────────────────────────────────

    class UploadResponse(BaseModel):
        manifest_id: str
        filename: str
        total_size: int
        num_chunks: int
        message: str = "File uploaded successfully"

    class FileEntry(BaseModel):
        manifest_id: str
        filename: str
        total_size: int

    class PeerEntry(BaseModel):
        node_id: str
        host: str
        port: int
        score: float

    class HealthResponse(BaseModel):
        node_id: str
        host: str
        port: int
        total_peers: int
        stored_chunks: int
        stored_bytes: int
        status: str = "ok"

    # ── File endpoints ────────────────────────────────────────────

    @app.post("/api/files/upload", response_model=UploadResponse, tags=["files"])
    async def upload_file(file: UploadFile = File(...)):
        """
        Upload a file to ZeroMesh.
        The file is chunked, encrypted with the node's key, and distributed.
        """
        METRICS.uploads_total.inc()
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "upload").suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            manifest_id = await node.file_manager.upload_file(
                tmp_path, node.key, filename=file.filename or tmp_path.name
            )
            manifest = await node.manifest_registry.get(manifest_id)
            if manifest is None:
                raise HTTPException(status_code=500, detail="Manifest not saved")

            METRICS.bytes_uploaded.inc(len(content))
            return UploadResponse(
                manifest_id=manifest_id,
                filename=manifest.filename,
                total_size=manifest.total_size,
                num_chunks=manifest.num_chunks,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.get("/api/files/{manifest_id}", tags=["files"])
    async def download_file(manifest_id: str):
        """Download a file by manifest_id. Returns the raw decrypted bytes."""
        METRICS.downloads_total.inc()
        manifest = await node.manifest_registry.get(manifest_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="Manifest not found")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".out") as tmp:
            out_path = Path(tmp.name)

        try:
            await node.file_manager.download_file(manifest_id, node.key, out_path)
            data = out_path.read_bytes()
            METRICS.bytes_downloaded.inc(len(data))
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="{manifest.filename}"'
                },
            )
        finally:
            out_path.unlink(missing_ok=True)

    @app.get("/api/files", response_model=list[FileEntry], tags=["files"])
    async def list_files():
        """List all files uploaded through this node."""
        entries = await node.manifest_registry.list_all()
        return [
            FileEntry(manifest_id=mid, filename=fn, total_size=ts)
            for mid, fn, ts in entries
        ]

    @app.delete("/api/files/{manifest_id}", tags=["files"])
    async def delete_file(manifest_id: str):
        """Remove a manifest (does not delete chunks from the network)."""
        deleted = await node.manifest_registry.delete(manifest_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Manifest not found")
        return {"message": "Manifest deleted", "manifest_id": manifest_id}

    # ── Peer endpoints ────────────────────────────────────────────

    @app.get("/api/peers", response_model=list[PeerEntry], tags=["peers"])
    async def list_peers():
        """List all known peers and their reliability scores."""
        peers = node.routing_table.all_peers()
        return [
            PeerEntry(
                node_id=p.node_id.hex,
                host=p.host,
                port=p.port,
                score=round(node.scorer.score(p.node_id.hex), 4),
            )
            for p in peers
        ]

    # ── Health endpoint ───────────────────────────────────────────

    @app.get("/api/health", response_model=HealthResponse, tags=["node"])
    async def health():
        """Node health and storage statistics."""
        return HealthResponse(
            node_id=node.local_id.hex,
            host=node.host,
            port=node.port,
            total_peers=node.routing_table.total_peers,
            stored_chunks=await node.chunk_store.total_chunks(),
            stored_bytes=await node.chunk_store.total_bytes(),
        )

    # ── Prometheus metrics ────────────────────────────────────────

    @app.get("/metrics", tags=["monitoring"], include_in_schema=False)
    async def prometheus_metrics():
        """Prometheus-compatible metrics endpoint."""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app
