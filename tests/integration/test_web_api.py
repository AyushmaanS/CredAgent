"""The web API in real Chrome against the fake provider (opt-in: CREDAGENT_BROWSER_TESTS=1), offline model stand-in.

These drive the same orchestrator the CLI does, through the HTTP API the page uses: start, follow, answer a handoff,
stop and resume, fail, and reveal a credential. A harness plays the person in the agent's own Chrome window.
"""

import json
import os

import pytest

from credagent.secrets.store import SecretFileStore
from tests.agent_harness import assert_no_leak
from tests.web_harness import Ui

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")


@pytest.fixture
def ui():
    u = Ui()
    yield u
    u.settle()
    u.close()


TERMS = ("(() => { const t = document.getElementById('accept-terms'); if (t) t.click();"
         " document.getElementById('create-app').click(); })()")


def test_a_run_without_handoffs_completes_and_a_secret_is_only_revealed_on_request(ui):
    run_id = ui.start("success")
    first = ui.view(run_id)
    assert first["state"] in ("running", "attention") and first["fake"]
    v = ui.wait(run_id, lambda v: v["state"] == "completed")
    res = v["result"]
    assert v["headline"] == "Credentials verified" and res["verification"]["label"] == "verified"
    assert [p["label"] for p in res["parts"]] == ["Client ID", "Client secret"]
    assert all(m["status"] == "done" for m in v["milestones"]) and v["activity"] is not None

    status, body = ui.call("POST", f"/api/runs/{run_id}/secrets/client_secret/reveal", {"confirm": True})
    stored = SecretFileStore(ui.settings.secrets_dir).get(
        ui.service.read_store.load(run_id).run.credential.parts["client_secret"].store_ref)
    issued = {a["client_secret"] for a in ui.fake_state(run_id)["apps"].values()} if "apps" in ui.fake_state(run_id) else set()
    assert status == 200 and body["value"] == stored and (not issued or stored in issued)
    # ...and nowhere else: not in the view, the list, the events, the config, or any run file
    everything = json.dumps([v, ui.call("GET", "/api/runs")[1], ui.call("GET", f"/api/runs/{run_id}/events?after=0")[1],
                             ui.call("GET", "/api/config")[1]])
    assert stored not in everything
    assert_no_leak(ui.settings.home, run_id, [stored])


def test_a_do_handoff_shows_what_to_do_and_continues_the_same_run(ui):
    run_id = ui.start("terms_checkbox")
    v = ui.wait(run_id, lambda v: v["state"] == "attention")
    a = v["attention"]
    assert a["type"] == "do" and a["title"] == "Your attention is needed" and a["headline"].startswith("Review and accept")
    assert "Enter" not in a["instruction"] and a["done_milestones"] and a["can_focus_browser"]
    assert ui.call("POST", f"/api/runs/{run_id}/continue", {"handoff_id": "h-stale"})[0] == 409  # not the open question
    assert ui.call("POST", "/api/runs", {"app": "Other", "mode": "fake", "scenario": "success"})[0] == 409  # one at a time
    ui.person(run_id, TERMS)
    assert ui.call("POST", f"/api/runs/{run_id}/continue", {"handoff_id": a["handoff_id"]})[0] == 200
    v = ui.wait(run_id, lambda v: v["state"] == "completed")
    assert v["id"] == run_id and v["result"]["verification"]["label"] == "verified"
    audit = ui.fake_state(run_id)["audit"]
    assert [x["actor"] for x in audit if x["event"] == "terms_accepted"] == ["person"]
    assert len([x for x in audit if x["event"] == "app_created"]) == 1


def test_a_decide_handoff_takes_one_of_the_offered_options(ui):
    run_id = ui.start("decide_app_type_and_scopes")
    v = ui.wait(run_id, lambda v: v["state"] == "attention")
    a = v["attention"]
    assert a["type"] == "decide" and len(a["options"]) >= 3 and a["options"][-1] == "Stop here"
    assert ui.call("POST", f"/api/runs/{run_id}/answer", {"handoff_id": a["handoff_id"], "option": 99})[0] == 400
    assert ui.call("POST", f"/api/runs/{run_id}/answer", {"handoff_id": a["handoff_id"], "option": "0"})[0] == 400
    assert ui.call("POST", f"/api/runs/{run_id}/answer", {"handoff_id": a["handoff_id"], "option": 0})[0] == 200
    ui.wait(run_id, lambda v: v["state"] != "attention" or v["attention"]["handoff_id"] != a["handoff_id"])


def test_stop_then_resume_keeps_the_run_and_the_browser_and_does_not_start_over(ui):
    run_id = ui.start("terms_checkbox")
    a = ui.wait(run_id, lambda v: v["state"] == "attention")["attention"]
    assert ui.call("POST", f"/api/runs/{run_id}/stop", {})[0] == 200
    paused = ui.wait(run_id, lambda v: v["state"] == "paused")
    assert paused["status"] == "running" and paused["paused"]["can_resume"] and paused["paused"]["done_so_far"]
    ui.settle()
    assert ui.call("POST", f"/api/runs/{run_id}/resume", {})[0] == 200
    again = ui.wait(run_id, lambda v: v["state"] == "attention")
    assert again["id"] == run_id and again["attention"]["type"] == "do"  # the page was re-checked, the same question
    ui.person(run_id, TERMS)
    assert ui.call("POST", f"/api/runs/{run_id}/continue", {"handoff_id": again["attention"]["handoff_id"]})[0] == 200
    v = ui.wait(run_id, lambda v: v["state"] == "completed")
    created = [x for x in ui.fake_state(run_id)["audit"] if x["event"] == "app_created"]
    assert len(created) == 1 and v["result"]["verification"]["label"] == "verified"  # never a second app
    assert a["handoff_id"] != again["attention"]["handoff_id"]


def test_a_failure_is_explained_and_marked_recoverable(ui):
    run_id = ui.start("service_unavailable")
    v = ui.wait(run_id, lambda v: v["state"] == "failed")
    f = v["failure"]
    assert f["kind"] == "recoverable" and f["can_resume"] and "service unavailable" in f["reason"].lower()
    assert f["next_steps"] and v["result"] is None and v["attention"] is None
    assert any(m["status"] == "failed" for m in v["milestones"])


def test_a_refresh_can_recover_any_run_because_state_is_read_from_the_backend(ui):
    run_id = ui.start("terms_checkbox")
    ui.wait(run_id, lambda v: v["state"] == "attention")
    other = Ui.__new__(Ui)  # a "new tab": same server, nothing carried over from the first client
    other.__dict__.update(ui.__dict__)
    assert other.view(run_id)["state"] == "attention"
    assert any(r["id"] == run_id for r in ui.call("GET", "/api/runs")[1]["runs"])
    ui.call("POST", f"/api/runs/{run_id}/stop", {})
