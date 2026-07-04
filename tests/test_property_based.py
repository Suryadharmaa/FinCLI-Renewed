"""Property-based tests using Hypothesis for FinCLI core modules."""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from fincli.app.utils.crypto import decrypt_broker_key, encrypt_broker_key
from fincli.app.utils.formatting import normalize_symbol

# ---------------------------------------------------------------------------
# crypto.py: encrypt/decrypt roundtrip
# ---------------------------------------------------------------------------


@given(
    plaintext=st.text(min_size=1, max_size=64).filter(lambda s: s.strip()),
    password=st.text(min_size=1, max_size=32).filter(lambda s: s.strip()),
)
@settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_encrypt_decrypt_roundtrip(plaintext: str, password: str) -> None:
    """Encrypting then decrypting should return the original plaintext."""
    encrypted = encrypt_broker_key(plaintext, password)
    decrypted = decrypt_broker_key(encrypted, password)
    assert decrypted == plaintext


@given(
    plaintext=st.text(min_size=1, max_size=64).filter(lambda s: s.strip()),
    password=st.text(min_size=1, max_size=32).filter(lambda s: s.strip()),
)
@settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_encrypted_output_differs_from_plaintext(plaintext: str, password: str) -> None:
    """Encrypted output should not equal the plaintext."""
    encrypted = encrypt_broker_key(plaintext, password)
    assert encrypted != plaintext


@given(
    plaintext=st.text(min_size=1, max_size=64).filter(lambda s: s.strip()),
    password=st.text(min_size=1, max_size=32).filter(lambda s: s.strip()),
    wrong_password=st.text(min_size=1, max_size=32).filter(lambda s: s.strip()),
)
@settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_wrong_password_fails(plaintext: str, password: str, wrong_password: str) -> None:
    """Decrypting with wrong password should raise ValueError."""
    assume(password != wrong_password)
    encrypted = encrypt_broker_key(plaintext, password)
    try:
        decrypt_broker_key(encrypted, wrong_password)
        raise AssertionError("Should have raised ValueError")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# formatting.py: normalize_symbol
# ---------------------------------------------------------------------------


@given(
    symbol=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Nd"), whitelist_characters=".-_^="),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_normalize_symbol_uppercases(symbol: str) -> None:
    """normalize_symbol should always return uppercase."""
    result = normalize_symbol(symbol)
    assert result == result.upper()


@given(
    symbol=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Nd"), whitelist_characters=".-_^="),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_normalize_symbol_strips_whitespace(symbol: str) -> None:
    """normalize_symbol should strip leading/trailing whitespace."""
    padded = f"  {symbol}  "
    result = normalize_symbol(padded)
    assert result == result.strip()


@given(
    symbol=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Nd"), whitelist_characters=".-_^="),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=100)
def test_normalize_symbol_idempotent(symbol: str) -> None:
    """normalize_symbol applied twice should equal applied once."""
    once = normalize_symbol(symbol)
    twice = normalize_symbol(once)
    assert once == twice
