import pytest
from app.crypto.aes import (
    b64_to_key,
    decrypt_chunk,
    encrypt_chunk,
    generate_key,
    key_to_b64,
)
from cryptography.exceptions import InvalidTag


def test_aes_encrypt_decrypt():
    key = generate_key()
    assert len(key) == 32

    key_b64 = key_to_b64(key)
    assert b64_to_key(key_b64) == key

    plain_data = b"ZeroMesh encrypted chunk payload test data"
    nonce, ciphertext = encrypt_chunk(plain_data, key)

    assert len(nonce) == 12
    assert ciphertext != plain_data

    decrypted = decrypt_chunk(ciphertext, key, nonce)
    assert decrypted == plain_data


def test_aes_tamper_detection():
    key = generate_key()
    plain_data = b"Secret chunk"
    nonce, ciphertext = encrypt_chunk(plain_data, key)

    # Tamper with ciphertext
    tampered_ciphertext = ciphertext[:-1] + (bytes([ciphertext[-1] ^ 0xFF]))

    with pytest.raises(InvalidTag):
        decrypt_chunk(tampered_ciphertext, key, nonce)
