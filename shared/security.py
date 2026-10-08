from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

PIN_ITERATIONS = 200_000
PIN_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class PinRecord:
    salt_hex: str
    key_hex: str


def create_nonce() -> str:
    return secrets.token_hex(32)


def create_salt() -> str:
    return secrets.token_hex(16)


def derive_pin_key(pin: str, salt_hex: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        pin.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PIN_ITERATIONS,
        dklen=PIN_KEY_BYTES,
    )


def create_pin_record(pin: str, salt_hex: str | None = None) -> PinRecord:
    salt = salt_hex or create_salt()
    key = derive_pin_key(pin, salt)
    return PinRecord(salt_hex=salt, key_hex=key.hex())


def sign_challenge(pin: str, salt_hex: str, nonce_hex: str) -> str:
    key = derive_pin_key(pin, salt_hex)
    return hmac.new(key, bytes.fromhex(nonce_hex), hashlib.sha256).hexdigest()


def verify_challenge_response(key_hex: str, nonce_hex: str, response_hex: str) -> bool:
    expected = hmac.new(
        bytes.fromhex(key_hex),
        bytes.fromhex(nonce_hex),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, response_hex)

