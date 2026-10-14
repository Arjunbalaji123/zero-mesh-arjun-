import pytest
from app.storage.chunker import calculate_sha256, chunk_file, reassemble_chunks


def test_chunk_file_and_reassemble():
    original_data = b"Hello ZeroMesh P2P Decentralized Encrypted File Storage System! " * 1000
    file_meta, chunks = chunk_file(original_data, filename="test.txt", chunk_size=1024)

    assert file_meta.file_size == len(original_data)
    assert file_meta.file_hash == calculate_sha256(original_data)
    assert len(chunks) > 1

    # Verify each chunk has correct seq number and sha256
    for idx, (meta, c_bytes) in enumerate(chunks):
        assert meta.sequence_number == idx
        assert meta.sha256_hash == calculate_sha256(c_bytes)

    # Reassemble and check match
    reconstructed = reassemble_chunks(chunks)
    assert reconstructed == original_data


def test_corrupted_chunk_detection():
    original_data = b"Corrupted Chunk Test Data " * 50
    _, chunks = chunk_file(original_data, filename="test_corrupt.txt", chunk_size=100)

    meta, c_bytes = chunks[0]
    corrupted_bytes = c_bytes[:-1] + b"X"

    corrupted_chunks = [(meta, corrupted_bytes)] + chunks[1:]

    with pytest.raises(ValueError, match="Integrity check failed"):
        reassemble_chunks(corrupted_chunks)
