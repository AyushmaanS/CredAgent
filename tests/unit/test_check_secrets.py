import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_secrets", Path(__file__).resolve().parents[2] / "scripts" / "check_secrets.py")
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)


def test_known_value_detected_and_not_echoed():
    val = "fr-local-key-value-987654"
    findings = cs.scan_text("a.py", f"x = '{val}'\n", [("FASTROUTER_API_KEY", val)])
    assert any("FASTROUTER_API_KEY" in f for f in findings)
    assert all(val not in f for f in findings)


def test_prefixed_key_detected():
    line = "token = 'ghp_" + "Z" * 30 + "'"
    assert cs.scan_text("a.py", line, [])


def test_allow_marker_and_plain_code_pass():
    assert not cs.scan_text("a.py", "api_key = settings.fastrouter_api_key\n", [])
    line = "k = 'ghp_" + "Z" * 30 + "'  # secret-scan: allow"
    assert not cs.scan_text("a.py", line, [])


def test_forbidden_paths():
    for p in [".env", ".env.local", "x/.env.prod", "k.pem", ".credagent/runs/x"]:
        assert cs.FORBIDDEN_PATH.search(p), p
    assert not cs.FORBIDDEN_PATH.search(".env.example")
