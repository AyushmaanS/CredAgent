from click.testing import CliRunner

from credagent.cli.main import NOT_IMPLEMENTED_EXIT, cli

COMMANDS = ["get", "resume", "status", "runs", "report", "verify", "secret"]


def test_help_lists_all_prd_commands():
    out = CliRunner().invoke(cli, ["--help"])
    assert out.exit_code == 0
    for c in COMMANDS:
        assert c in out.output


def test_unimplemented_commands_never_claim_success():
    r = CliRunner().invoke(cli, ["get", "GitHub"])
    assert r.exit_code == NOT_IMPLEMENTED_EXIT
    assert "not implemented" in r.output


def test_get_validates_app_name():
    r = CliRunner().invoke(cli, ["get", "   "])
    assert r.exit_code != 0 and "app name" in r.output
