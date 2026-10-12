# ZeroMesh 🕸️

> **Decentralized Peer-to-Peer Encrypted File System**  
> Built with Python · AES-256-GCM · Kademlia DHT · SHA-256 · AsyncIO

---

## Architecture

```
Raw File → Chunking → SHA-256 Hash → AES-256-GCM Encrypt → Kademlia DHT → Peers
                                                                              ↓
                                                                   Parallel Retrieval
                                                                              ↓
                                               Decrypt → Verify Hash → Reassembled File
```

## Module Map

| Module | Responsibility |
|--------|---------------|
| `zeromesh/crypto/` | AES-256-GCM encryption, SHA-256 hashing |
| `zeromesh/core/` | File chunking, chunk metadata, assembler |
| `zeromesh/dht/` | Kademlia routing table, XOR metric, K-buckets, RPCs |
| `zeromesh/network/` | Async TCP engine, framing protocol, peer manager |
| `zeromesh/storage/` | Local chunk store, SQLite index |
| `zeromesh/api/` | FastAPI REST interface |
| `zeromesh/monitoring/` | Prometheus metrics, structured logging |

## Quick Start

```bash
# 1. Create virtualenv
python -m venv .venv
source .venv/bin/activate

# 2. Install deps
pip install -e ".[dev]"

# 3. Run a node
zeromesh node start --port 7400

# 4. Upload a file
zeromesh file upload ./myfile.txt

# 5. Download a file
zeromesh file download <file-hash> --out ./recovered.txt
```

## Development Phases

- [ ] **Phase 1:** Crypto engine — Chunking + SHA-256 + AES-256-GCM
- [ ] **Phase 2:** Framing protocol — Async TCP + message types
- [ ] **Phase 3:** Kademlia DHT — XOR distance, K-buckets, lookups
- [ ] **Phase 4:** Distributed storage — STORE/FIND_VALUE, replication
- [ ] **Phase 5:** Parallel retrieval — Concurrent chunk download + assembly
- [ ] **Phase 6:** REST API + CLI
- [ ] **Phase 7:** Monitoring, benchmarks, chaos testing

## License

MIT
