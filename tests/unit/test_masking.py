import pytest

from credagent.secrets.masking import Masker, masked_display

FAKE_GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"  # built at runtime so the scanner is not tripped


def test_registered_value_is_replaced_and_not_leaked():
    secret = "zq8Vn2-fake-client-secret-Lk3P"  # fake; secret-scan: allow
    m = Masker([secret])
    out = m.mask_text(f"your secret is {secret}.")
    assert secret not in out
    assert "[REDACTED:secret]" in out


def test_prefixed_key_masked_without_registration():
    out = Masker().mask_text(f"token={FAKE_GH}")
    assert FAKE_GH not in out


def test_labelled_secret_masked():
    out = Masker().mask_text("Client secret: Xy7pQ9rT2vW4zA6b")
    assert "Xy7pQ9rT2vW4zA6b" not in out
    assert out.startswith("Client secret: [REDACTED")


def test_high_entropy_token_masked_but_plain_words_kept():
    tok = "Qm9yZ2VkLXNlY3JldC1mb3ItdGVzdGluZy0xMjM0NTY3OA"
    out = Masker().mask_text(f"value {tok} and the word configuration")
    assert tok not in out
    assert "configuration" in out


def test_nested_structures_masked():
    secret = "nested-fake-secret-value-123"  # fake; secret-scan: allow
    m = Masker([secret])
    data = {"messages": [{"content": f"x {secret}"}], "k": (secret,)}
    out = m.mask(data)
    assert secret not in repr(out)


def test_short_secret_refused():
    with pytest.raises(ValueError):
        Masker().register("abc")


def test_masked_display_reveals_little():
    assert masked_display("short-secret") == "•••(12 chars)"
    long = "abcd" + "x" * 30
    assert masked_display(long).startswith("abcd…")
    assert "x" * 5 not in masked_display(long)
