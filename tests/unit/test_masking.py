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


def test_hex_secret_masked():
    import secrets
    hex40 = secrets.token_hex(20)  # like a 40-char hex client secret
    out = Masker().mask_text(f"Client secret {hex40} shown once")
    assert hex40 not in out


def test_research_urls_survive_masking():
    urls = [
        "https://community.openai.com/t/how-do-i-get-an-api-key-for-my-project/1234567",
        "https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app",
        "https://forums.developer.nvidia.com/t/where-to-find-developer-api-keys/2024123",
        "https://support.example.test/en/articles/8128613-api-keys-create-api-keys-for-3rd-party-apps",
    ]
    for u in urls:
        assert Masker().mask_text(f"see {u} for details") == f"see {u} for details"


def test_secret_inside_url_still_masked():
    import secrets
    tok = secrets.token_urlsafe(30)
    out = Masker().mask_text(f"https://api.example.test/cb?code=x&state={tok}")
    assert tok not in out and out.startswith("https://api.example.test/cb?code=x&state=")
    assert "client_secret=" in Masker().mask_text("https://x.test/t?client_secret=Ab12Cd34Ef56Gh78")
    assert "Ab12Cd34Ef56Gh78" not in Masker().mask_text("https://x.test/t?client_secret=Ab12Cd34Ef56Gh78")


def test_base64_secret_with_slash_outside_url_masked():
    import base64
    import secrets
    b64 = base64.b64encode(secrets.token_bytes(30)).decode()  # may contain / and +
    assert b64 not in Masker().mask_text(f"secret access key {b64}")


def test_labelled_prose_is_not_masked():
    for prose in ["token: Fine-grained personal access token", "api key: Internal connection token",
                  "Password: Required"]:
        assert Masker().mask_text(prose) == prose
    assert "Ab12Cd34Ef56" not in Masker().mask_text("api_key=Ab12Cd34Ef56")
    assert "abcdefghijklmnopqrstuvwxyz" not in Masker().mask_text("token: abcdefghijklmnopqrstuvwxyz")
