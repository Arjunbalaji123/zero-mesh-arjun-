"""
Unit tests — Phase 1: Crypto Engine + Chunker
"""

import tempfile
from pathlib import Path

import pytest

from zeromesh.crypto.engine import (
    KEY_SIZE_BYTES,
    decrypt_chunk,
    derive_key,
    encrypt_chunk,
    generate_key,
    sha256_hash,
    verify_hash,
)
from zeromesh.core.chunker import FileAssembler, FileChunker, FileManifest


# ─── Crypto Tests ─────────────────────────────────────────────────────────────

class TestSha256:
    def test_known_hash(self):
        # echo -n "" | sha256sum → e3b0...
        assert sha256_hash(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_different_data_different_hash(self):
        assert sha256_hash(b"hello") != sha256_hash(b"world")

    def test_verify_hash_correct(self):
        data = b"zeromesh test data"
        h = sha256_hash(data)
        assert verify_hash(data, h) is True

    def test_verify_hash_tampered(self):
        data = b"zeromesh test data"
        h = sha256_hash(data)
        tampered = b"zeromesh TEST data"
        assert verify_hash(tampered, h) is False


class TestKeyGeneration:
    def test_generate_key_length(self):
        key = generate_key()
        assert len(key) == KEY_SIZE_BYTES

    def test_generate_keys_are_unique(self):
        keys = {generate_key() for _ in range(100)}
        assert len(keys) == 100  # no collisions

    def test_derive_key_reproducible(self):
        passphrase = "correct-horse-battery-staple"
        key1, salt = derive_key(passphrase)
        key2, _ = derive_key(passphrase, salt=salt)
        assert key1 == key2

    def test_derive_key_different_salts(self):
        passphrase = "same-passphrase"
        key1, _ = derive_key(passphrase)
        key2, _ = derive_key(passphrase)
        # Different salts → different keys (birthday attack defence)
        assert key1 != key2


class TestEncryptDecrypt:
    def test_roundtrip(self):
        key = generate_key()
        plaintext = b"Hello, ZeroMesh!"
        enc = encrypt_chunk(plaintext, key)
        recovered = decrypt_chunk(enc, key)
        assert recovered == plaintext

    def test_content_id_matches_plaintext_hash(self):
        key = generate_key()
        plaintext = b"content-addressed chunk"
        enc = encrypt_chunk(plaintext, key)
        assert enc.content_id == sha256_hash(plaintext)

    def test_ciphertext_differs_from_plaintext(self):
        key = generate_key()
        plaintext = b"secret data"
        enc = encrypt_chunk(plaintext, key)
        assert enc.ciphertext != plaintext

    def test_unique_nonces_per_encryption(self):
        key = generate_key()
        plaintext = b"same plaintext"
        enc1 = encrypt_chunk(plaintext, key)
        enc2 = encrypt_chunk(plaintext, key)
        # Same plaintext + same key → DIFFERENT nonces and ciphertexts
        assert enc1.nonce != enc2.nonce
        assert enc1.ciphertext != enc2.ciphertext

    def test_tampered_ciphertext_raises(self):
        from cryptography.exceptions import InvalidTag

        key = generate_key()
        enc = encrypt_chunk(b"authentic data", key)

        # Flip a byte in the ciphertext (simulates network corruption / attack)
        tampered_ct = bytearray(enc.ciphertext)
        tampered_ct[0] ^= 0xFF
        from zeromesh.crypto.engine import EncryptedChunk
        tampered = EncryptedChunk(
            nonce=enc.nonce,
            ciphertext=bytes(tampered_ct),
            content_id=enc.content_id,
        )
        with pytest.raises(InvalidTag):
            decrypt_chunk(tampered, key)

    def test_wrong_key_raises(self):
        from cryptography.exceptions import InvalidTag

        key1 = generate_key()
        key2 = generate_key()
        enc = encrypt_chunk(b"secret", key1)
        with pytest.raises(InvalidTag):
            decrypt_chunk(enc, key2)

    def test_invalid_key_size_raises(self):
        with pytest.raises(ValueError, match="Key must be"):
            encrypt_chunk(b"data", key=b"tooshort")

    def test_large_chunk(self):
        key = generate_key()
        plaintext = bytes(range(256)) * 1024  # 256 KB
        enc = encrypt_chunk(plaintext, key)
        assert decrypt_chunk(enc, key) == plaintext


# ─── Chunker Tests ────────────────────────────────────────────────────────────

class TestFileChunker:
    def _make_tmpfile(self, size_bytes: int) -> Path:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        tmp.write(bytes(range(256)) * (size_bytes // 256) + b"\x00" * (size_bytes % 256))
        tmp.flush()
        return Path(tmp.name)

    def test_chunk_count_exact_multiple(self):
        path = self._make_tmpfile(512 * 1024)  # exactly 2 chunks of 256 KB
        chunker = FileChunker(chunk_size=256 * 1024)
        manifest, chunks = chunker.chunk_file(path)
        assert len(chunks) == 2
        assert manifest.num_chunks == 2

    def test_chunk_count_with_remainder(self):
        path = self._make_tmpfile(300 * 1024)  # 256 KB + 44 KB
        chunker = FileChunker(chunk_size=256 * 1024)
        manifest, chunks = chunker.chunk_file(path)
        assert len(chunks) == 2
        assert len(chunks[0]) == 256 * 1024
        assert len(chunks[1]) == 44 * 1024

    def test_manifest_id_stable(self):
        path = self._make_tmpfile(100 * 1024)
        chunker = FileChunker()
        m1, _ = chunker.chunk_file(path)
        m2, _ = chunker.chunk_file(path)
        assert m1.manifest_id == m2.manifest_id

    def test_chunk_content_ids_match_sha256(self):
        path = self._make_tmpfile(50 * 1024)
        chunker = FileChunker(chunk_size=20 * 1024)
        manifest, chunks = chunker.chunk_file(path)
        for meta, chunk in zip(manifest.chunks, chunks):
            assert meta.content_id == sha256_hash(chunk)

    def test_file_not_found(self):
        chunker = FileChunker()
        with pytest.raises(FileNotFoundError):
            chunker.chunk_file(Path("/nonexistent/file.txt"))


class TestFileAssembler:
    def test_roundtrip_reassembly(self):
        # Create a temp file, chunk it, then reassemble and compare
        original_data = b"ZeroMesh file content. " * 5000
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(original_data)
            src = Path(f.name)

        chunker = FileChunker(chunk_size=1024)
        manifest, chunks = chunker.chunk_file(src)

        assembler = FileAssembler(manifest)
        for i, chunk in enumerate(chunks):
            assembler.add_chunk(i, chunk)

        assert assembler.is_complete

        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            out = Path(f.name)
        assembler.write_to(out)

        assert out.read_bytes() == original_data

    def test_missing_chunks_reported(self):
        path = tempfile.NamedTemporaryFile(delete=False)
        path_obj = Path(path.name)
        path_obj.write_bytes(b"x" * 300 * 1024)

        chunker = FileChunker(chunk_size=100 * 1024)
        manifest, chunks = chunker.chunk_file(path_obj)

        assembler = FileAssembler(manifest)
        assembler.add_chunk(0, chunks[0])
        # Don't add chunks 1 and 2
        assert assembler.missing_indices == [1, 2]
        assert not assembler.is_complete

    def test_tampered_chunk_rejected(self):
        path = tempfile.NamedTemporaryFile(delete=False)
        path_obj = Path(path.name)
        path_obj.write_bytes(b"authentic content " * 100)

        chunker = FileChunker(chunk_size=512)
        manifest, chunks = chunker.chunk_file(path_obj)

        assembler = FileAssembler(manifest)
        tampered = bytearray(chunks[0])
        tampered[0] ^= 0xFF

        with pytest.raises(ValueError, match="integrity failure"):
            assembler.add_chunk(0, bytes(tampered))

    def test_out_of_order_chunks_assemble_correctly(self):
        data = b"abcdefgh" * 1000
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            src = Path(f.name)

        chunker = FileChunker(chunk_size=1024)
        manifest, chunks = chunker.chunk_file(src)

        assembler = FileAssembler(manifest)
        # Add in reverse order
        for i in reversed(range(len(chunks))):
            assembler.add_chunk(i, chunks[i])

        assert assembler.is_complete

        with tempfile.NamedTemporaryFile(delete=False) as f:
            out = Path(f.name)
        assembler.write_to(out)
        assert out.read_bytes() == data
