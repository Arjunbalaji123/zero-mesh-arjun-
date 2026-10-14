import base64
import os
from typing import Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_key() -> bytes:
    """Generates a secure 256-bit (32 bytes) AES key."""
    return AESGCM.generate_key(bit_length=256)


def key_to_b64(key: bytes) -> str:
    """Converts key bytes to base64 string for metadata storage."""
    return base64.b64encode(key).decode("utf-8")


def b64_to_key(key_b64: str) -> bytes:
    """Converts base64 string back to key bytes."""
    return base64.b64decode(key_b64.encode("utf-8"))


def encrypt_chunk(chunk_bytes: bytes, key: bytes) -> Tuple[bytes, bytes]:
    """
    Encrypts a chunk using AES-256-GCM with a unique 96-bit (12 bytes) nonce.
    Returns (nonce, ciphertext_with_tag).
    """
    nonce = os.urandom(12)  # Standard 12-byte GCM nonce
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, chunk_bytes, associated_data=None)
    return nonce, ciphertext


def decrypt_chunk(ciphertext: bytes, key: bytes, nonce: bytes) -> bytes:
    """
    Decrypts AES-256-GCM ciphertext using the given key and nonce.
    Raises InvalidTag if tampered or invalid key/nonce.
    """
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, associated_data=None)
