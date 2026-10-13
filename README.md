# ZeroMesh 🕸️

> **Decentralized Peer-to-Peer Encrypted File System**  
> Built from scratch in Python 3.12+ · AES-256-GCM · Kademlia DHT · SHA-256 · AsyncIO · FastAPI · Prometheus

[![Tests](https://img.shields.io/badge/tests-125%20passed-brightgreen.svg)]()
[![Encryption](https://img.shields.io/badge/crypto-AES--256--GCM-blue.svg)]()
[![DHT](https://img.shields.io/badge/DHT-Kademlia%20(256--bit)-purple.svg)]()
[![Throughput](https://img.shields.io/badge/throughput-1.5%20GB%2Fs-orange.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()

---

## 🌟 Overview

ZeroMesh is a high-performance, fully decentralized peer-to-peer storage network. Files uploaded to ZeroMesh are sliced into content-addressed chunks, encrypted with military-grade AES-256-GCM, hashed with SHA-256 for tamper detection, and distributed across a Kademlia Distributed Hash Table (DHT) network.

Downloads execute via concurrent DHT lookups, gathering chunks from the closest peers simultaneously with automatic fault tolerance and dynamic peer reliability scoring.

---

## 🏗️ Architecture

```
                                  [ Upload Workflow ]
  Source File ──► FileChunker (256 KB) ──► SHA-256 Hash ──► AES-256-GCM Encrypt
                                                                      │
                                                     ┌────────────────┴────────────────┐
                                                     ▼                                 ▼
                                            Local SQLite Store             Kademlia STORE_CHUNK RPC
                                            (sharded flat files)            (3x peer replication)

                                 [ Download Workflow ]
  Manifest ID ──► Parallel DHT Lookup ──► GET_CHUNK RPCs (fastest peers) ──► Decrypt & Verify
                                                                                     │
                                                                                     ▼
                                                                           FileAssembler ──► File
```

---

## 📦 System Modules

| Subsystem | Location | Description |
|-----------|----------|-------------|
| **Cryptography** | [`zeromesh/crypto/`](file:///home/shivesh/zeromesh/zeromesh/crypto/) | AES-256-GCM authenticated cipher with 12-byte random nonces and SHA-256 hashing. |
| **Chunking Engine** | [`zeromesh/core/`](file:///home/shivesh/zeromesh/zeromesh/core/) | Deterministic file chunker, `FileManifest`, and stream reassembler with hash verification. |
| **Kademlia DHT** | [`zeromesh/dht/`](file:///home/shivesh/zeromesh/zeromesh/dht/) | 256-bit `NodeID`, XOR metric distance, 256 K-Buckets ($k=20$), and iterative `FIND_NODE` lookup ($\alpha=3$). |
| **Async TCP Framing** | [`zeromesh/network/`](file:///home/shivesh/zeromesh/zeromesh/network/) | Binary MsgPack wire protocol over length-prefixed frames, async TCP connection pool, and `PeerScorer`. |
| **Storage Engine** | [`zeromesh/storage/`](file:///home/shivesh/zeromesh/zeromesh/storage/) | `LocalChunkStore` (WAL-mode SQLite + 2-char directory prefix sharding) and `ManifestRegistry`. |
| **Integration Node** | [`zeromesh/node.py`](file:///home/shivesh/zeromesh/zeromesh/node.py) | Full `ZeroMeshNode` coordinating network, DHT, storage engine, and replication. |
| **REST API** | [`zeromesh/api/`](file:///home/shivesh/zeromesh/zeromesh/api/) | FastAPI application with file upload/download, peer tracking, health stats, and OpenAPI Swagger docs. |
| **CLI & Telemetry** | [`zeromesh/cli.py`](file:///home/shivesh/zeromesh/zeromesh/cli.py), [`zeromesh/monitoring/`](file:///home/shivesh/zeromesh/zeromesh/monitoring/) | Rich interactive CLI commands and Prometheus metrics registry (`/metrics`). |

---

## 🚀 Performance Benchmarks

Measured on a standard modern workstation using `benchmarks/benchmark_throughput.py`:

```
                    Subsystem Performance Summary                     
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Subsystem / Operation          ┃ Workload           ┃   Throughput ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ SHA-256 Hashing                │ 50 MB              │ 1,566.9 MB/s │
│ AES-256-GCM Encryption         │ 50 MB              │ 1,184.7 MB/s │
│ AES-256-GCM Decryption         │ 50 MB              │ 1,177.6 MB/s │
│ File Chunker (256 KB chunks)   │ 50 MB (200 chunks) │   964.9 MB/s │
│ File Assembler + Verification  │ 50 MB (200 chunks) │ 1,133.6 MB/s │
│ Async Chunk Store (Write+Read) │ 25 MB + 25 MB      │ 1,284.8 MB/s │
└────────────────────────────────┴────────────────────┴──────────────┘
```

---

## 💻 Quickstart

### 1. Installation

```bash
git clone https://github.com/Arjunbalaji123/zero-mesh.git
cd zero-mesh
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Start a ZeroMesh Node

```bash
# Starts P2P node on port 7400, REST API on port 8000
zeromesh start --port 7400 --api-port 8000 --data-dir ./data
```

To join an existing network, provide one or more seed bootstrap peers:

```bash
zeromesh start --port 7401 --api-port 8001 --data-dir ./data_node2 --bootstrap 127.0.0.1:7400
```

### 3. File Operations (CLI)

```bash
# Upload a file
zeromesh upload ./my_secret_file.pdf

# List stored files
zeromesh list-files

# Download and decrypt a file
zeromesh download <manifest_id> ./downloaded_file.pdf

# Inspect known DHT peers and reliability scores
zeromesh peers

# Node telemetry and storage health
zeromesh status
```

---

## 🌐 Web Console & REST API

ZeroMesh includes a **Cyberpunk Glassmorphic Web Dashboard** served directly at `http://127.0.0.1:8000/` (interactive API documentation at `/docs`):

- **Web Dashboard**: `http://127.0.0.1:8000/` — Drag-and-drop file upload, instant P2P downloads, real-time DHT peer routing table, live telemetry metrics, and retro-cyber event console.
- `POST /api/files/upload`: Multipart upload with automatic chunking and distribution
- `GET /api/files/{manifest_id}`: Parallel download, verification, and streaming response
- `GET /api/files`: List all files registered on the node
- `DELETE /api/files/{manifest_id}`: Remove file manifest
- `GET /api/peers`: List discovered DHT peers and live reliability scores
- `GET /api/health`: Node status, peer count, and stored storage volume
- `GET /metrics`: Standard Prometheus metrics scrape target

---

## 🧪 Testing

The repository features 100% test pass rate across 124 unit and multi-node integration tests:

```bash
# Run entire test suite
pytest tests/ -v

# Run multi-node integration cluster test
pytest tests/integration/test_multinode_network.py -v

# Run performance benchmark suite
python benchmarks/benchmark_throughput.py
```

---

## 📋 Implementation Checklist

- [x] **Phase 1: Cryptography & Chunker**
  - [x] AES-256-GCM authenticated cipher with 12-byte random IV
  - [x] SHA-256 content address hashing
  - [x] Streaming file chunker and tamper-resistant assembler
- [x] **Phase 2: Network & Framing**
  - [x] 5-byte fixed header binary framing protocol (Length + Type)
  - [x] Async TCP full-duplex connection manager with MsgPack serialization
  - [x] Peer reliability scoring algorithm with exponential penalty & RTT weighting
- [x] **Phase 3: Kademlia DHT**
  - [x] 256-bit NodeID with XOR distance calculation and MSB bucket indexing
  - [x] 256 K-Buckets ($k=20$) with least-recently seen eviction and replacement cache
  - [x] Routing table with closest-k neighbor query
  - [x] Iterative `FIND_NODE` lookup algorithm ($\alpha=3$)
- [x] **Phase 4: Distributed Storage Engine**
  - [x] `LocalChunkStore` with 2-char prefix directory sharding and SQLite metadata
  - [x] `ManifestRegistry` for persistent file manifests
  - [x] `FileManager` upload/download pipeline with 3x replication factor
- [x] **Phase 5: Node Integration**
  - [x] Complete `ZeroMeshNode` coordinating network, DHT, storage, and scoring
  - [x] Inter-node RPC dispatching: PING, PONG, FIND_NODE, STORE_CHUNK, GET_CHUNK
  - [x] Network bootstrap and periodic peer refresh
- [x] **Phase 6: REST API & CLI**
  - [x] FastAPI REST interface with CORS, swagger docs, and streaming
  - [x] Typer + Rich CLI with start, upload, download, list-files, peers, and status
- [x] **Phase 7: Monitoring & Benchmarking**
  - [x] Prometheus metrics registry and `/metrics` endpoint
  - [x] Throughput benchmarks (~1.5 GB/s SHA-256, ~1.2 GB/s AES-256-GCM)
  - [x] Multi-node 3-cluster integration test

---

## 📄 License

MIT © [shivesh4106-prog](https://github.com/shivesh4106-prog)
