"""
ZeroMesh Performance Benchmarks
================================
Measures throughput and latency across key subsystems:
  1. Cryptographic throughput: AES-256-GCM encryption & decryption (MB/s)
  2. Hashing throughput: SHA-256 (MB/s)
  3. Chunking & Assembly throughput (MB/s)
  4. Local chunk storage persistence speed (chunks/s, MB/s)
  5. Local async P2P loopback throughput (MB/s)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from zeromesh.core.chunker import FileAssembler, FileChunker
from zeromesh.crypto.engine import decrypt_chunk, encrypt_chunk, generate_key, sha256_hash
from zeromesh.storage.chunk_store import LocalChunkStore

console = Console()


def benchmark_crypto(size_mb: int = 50) -> tuple[float, float, float]:
    """Benchmark SHA-256, AES-256-GCM Encrypt, and Decrypt."""
    data = os.urandom(size_mb * 1024 * 1024)
    key = generate_key()

    # SHA-256
    t0 = time.perf_counter()
    sha256_hash(data)
    t_sha = time.perf_counter() - t0
    sha_speed = size_mb / t_sha

    # AES-256-GCM Encrypt
    t0 = time.perf_counter()
    enc = encrypt_chunk(data, key)
    t_enc = time.perf_counter() - t0
    enc_speed = size_mb / t_enc

    # AES-256-GCM Decrypt
    t0 = time.perf_counter()
    decrypt_chunk(enc, key)
    t_dec = time.perf_counter() - t0
    dec_speed = size_mb / t_dec

    return sha_speed, enc_speed, dec_speed


def benchmark_chunker(size_mb: int = 50) -> tuple[float, float]:
    """Benchmark FileChunker and FileAssembler throughput."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        data = os.urandom(size_mb * 1024 * 1024)
        f.write(data)
        f_path = Path(f.name)

    try:
        chunker = FileChunker(chunk_size=256 * 1024)
        t0 = time.perf_counter()
        manifest, raw_chunks = chunker.chunk_file(f_path)
        t_chunk = time.perf_counter() - t0
        chunk_speed = size_mb / t_chunk

        assembler = FileAssembler(manifest)
        t0 = time.perf_counter()
        for i, c in enumerate(raw_chunks):
            assembler.add_chunk(i, c)
        with tempfile.NamedTemporaryFile(delete=False) as out_f:
            out_p = Path(out_f.name)
        assembler.write_to(out_p)
        t_asm = time.perf_counter() - t0
        asm_speed = size_mb / t_asm
        out_p.unlink(missing_ok=True)

        return chunk_speed, asm_speed
    finally:
        f_path.unlink(missing_ok=True)


async def benchmark_storage(num_chunks: int = 100, chunk_kb: int = 256) -> float:
    """Benchmark LocalChunkStore put/get throughput."""
    with tempfile.TemporaryDirectory() as td:
        store = LocalChunkStore(Path(td))
        await store.open()

        chunks = [(f"chunk_{i:04d}" * 8, os.urandom(12), os.urandom(chunk_kb * 1024)) for i in range(num_chunks)]
        total_mb = (num_chunks * chunk_kb) / 1024.0

        t0 = time.perf_counter()
        for cid, nonce, ct in chunks:
            await store.put(cid, nonce, ct)
        for cid, _, _ in chunks:
            await store.get(cid)
        t_tot = time.perf_counter() - t0

        await store.close()
        return (total_mb * 2) / t_tot  # read + write throughput


def run_all_benchmarks():
    console.print("\n[bold cyan]⚡ Running ZeroMesh Performance Benchmarks ⚡[/bold cyan]\n")

    table = Table(title="Subsystem Performance Summary")
    table.add_column("Subsystem / Operation", style="yellow")
    table.add_column("Workload", style="cyan")
    table.add_column("Throughput", justify="right", style="green")

    # 1. Crypto
    console.print("[dim]Benchmarking Cryptography & Hashing (50 MB)...[/dim]")
    sha_mb, enc_mb, dec_mb = benchmark_crypto(50)
    table.add_row("SHA-256 Hashing", "50 MB", f"{sha_mb:,.1f} MB/s")
    table.add_row("AES-256-GCM Encryption", "50 MB", f"{enc_mb:,.1f} MB/s")
    table.add_row("AES-256-GCM Decryption", "50 MB", f"{dec_mb:,.1f} MB/s")

    # 2. Chunker
    console.print("[dim]Benchmarking File Chunking & Assembly (50 MB)...[/dim]")
    chunk_mb, asm_mb = benchmark_chunker(50)
    table.add_row("File Chunker (256 KB chunks)", "50 MB (200 chunks)", f"{chunk_mb:,.1f} MB/s")
    table.add_row("File Assembler + Verification", "50 MB (200 chunks)", f"{asm_mb:,.1f} MB/s")

    # 3. Storage
    console.print("[dim]Benchmarking Local Storage Engine (100 x 256KB chunks)...[/dim]")
    storage_mb = asyncio.run(benchmark_storage(100, 256))
    table.add_row("Async Chunk Store (Write+Read)", "25 MB + 25 MB", f"{storage_mb:,.1f} MB/s")

    console.print(table)
    console.print("\n[bold green]✓ Benchmarks Completed Successfully![/bold green]\n")


if __name__ == "__main__":
    run_all_benchmarks()
