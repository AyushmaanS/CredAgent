"""Agent snapshot (D-078 phase 1): numbered refs, hidden secrets, compact rendering, change description."""

from credagent.browser.snapshot import MAX_ELEMENTS, TEXT_CHARS, build_snapshot, describe_change
from credagent.secrets.masking import Masker

SECRET = "fpcs_" + "Zx9" * 14


def el(xpath, role, name, **kw):
    d = {"xpath": xpath, "tag": "a", "role": role, "name": name, "type": "", "href": "", "disabled": False,
         "checked": False, "readonly": False, "value_len": 0, "section": "", "options": [], "in_dialog": False,
         "in_view": True}
    d.update(kw)
    return d


def raw(elements, **kw):
    base = {"url": "http://127.0.0.1:1/apps/42/oauth2", "title": "OAuth2", "text": "Client ID Redirects",
            "inputs": [], "buttons": [], "links": [], "forms": [], "banners": [], "headings": ["OAuth2", "Redirects"],
            "iframes": [], "secret_xpaths": [], "elements": elements, "scroll": {"y": 0, "height": 2000, "view": 800}}
    base.update(kw)
    return base


def test_refs_are_sequential_in_document_order_and_resolve():
    s = build_snapshot(raw([el("/a[1]", "link", "OAuth2", href="http://127.0.0.1:1/apps/42/oauth2"),
                            el("/b[1]", "button", "Add Redirect", tag="button"),
                            el("/i[1]", "field", "Select redirect URI", tag="input", type="text", section="Redirects")]),
                       Masker())
    assert [e.ref for e in s.elements] == ["e1", "e2", "e3"]
    assert s.element("e2").name == "Add Redirect" and s.element(" E3 ").role == "field"
    assert s.element("e9") is None and s.element(None) is None


def test_render_is_compact_and_never_contains_values_or_secrets():
    m = Masker()
    m.register(SECRET, "client_secret")
    s = build_snapshot(raw([
        el("/i[1]", "field", "Client secret", tag="input", type="text", value_len=len(SECRET)),
        el("/i[2]", "field", "Password", tag="input", type="password"),
        el("/c[1]", "checkbox", "identify", tag="input", type="checkbox", checked=True),
        el("/s[1]", "select", "App type", tag="select", options=["Web app", "SPA"]),
        el("/l[1]", "link", f"copy {SECRET}", href="http://127.0.0.1:1/docs"),  # a secret that slipped into a name
    ], text=f"Your secret is {SECRET}", secret_xpaths=["/code[1]"]), m)
    out = s.render()
    assert SECRET not in out
    assert 'e1 field "Client secret" [filled]' in out and "(password)" in out
    assert 'e3 checkbox "identify" [checked]' in out and "options: Web app | SPA" in out
    assert "credential-like value(s) are on this page and are hidden" in out
    assert "→ /docs" in out  # same-origin links are shown as paths


def test_render_keeps_structure_when_trimmed_and_caps_elements():
    many = [el(f"/b[{i}]", "button", f"Button {i}", tag="button") for i in range(MAX_ELEMENTS + 30)]
    s = build_snapshot(raw(many, text="x" * 20_000), Masker())
    assert len(s.elements) == MAX_ELEMENTS and s.truncated == 30
    out = s.render(max_chars=6000)
    assert out.startswith("URL:") and len(out) <= 6000 and "[…trimmed]" in out
    assert "Elements (200, +30 more not shown):" in s.render()
    assert len(build_snapshot(raw([], text="y" * 20_000), Masker()).render()) < TEXT_CHARS + 400


def snap(url="http://127.0.0.1:1/apps/42", elements=(), **kw):
    return build_snapshot(raw(list(elements), url=url, **kw), Masker())


def test_describe_change():
    a = snap(elements=[el("/b[1]", "button", "Add Redirect", tag="button")])
    assert describe_change(None, a) == "first look at the page"
    assert describe_change(a, snap(elements=[el("/b[1]", "button", "Add Redirect", tag="button")])) == "no change"
    nav = snap(url="http://127.0.0.1:1/apps/42/oauth2", elements=[el("/b[1]", "button", "Add Redirect", tag="button")])
    assert describe_change(a, nav).startswith("navigated to /apps/42/oauth2")
    grown = snap(elements=[el("/b[1]", "button", "Add Redirect", tag="button"),
                           el("/i[1]", "field", "redirect", tag="input", section="Redirects")])
    assert "1 new element(s): field “redirect”" in describe_change(a, grown)
    gone = snap(elements=[])
    assert "element(s) gone: button “Add Redirect”" in describe_change(a, gone)
    dlg = snap(elements=[el("/b[1]", "button", "Add Redirect", tag="button")], banners=[
        {"xpath": "/d", "text": "Reset the client secret? Any old secret stops working."}])
    assert "a dialog appeared: Reset the client secret" in describe_change(a, dlg)
    assert describe_change(dlg, a) == "a dialog closed"


def test_describe_change_reports_fields_checkboxes_and_secrets_appearing():
    f0 = snap(elements=[el("/i[1]", "field", "Name", tag="input", type="text"),
                        el("/c[1]", "checkbox", "identify", tag="input", type="checkbox")])
    f1 = snap(elements=[el("/i[1]", "field", "Name", tag="input", type="text", value_len=5),
                        el("/c[1]", "checkbox", "identify", tag="input", type="checkbox", checked=True)],
              secret_xpaths=["/code[1]"])
    out = describe_change(f0, f1)
    assert "field “Name” is now filled" in out and "“identify” is now checked" in out
    assert "credential-like values appeared" in out


def test_custom_dropdown_roles_are_listed_and_the_choice_is_a_decide_d097():
    from credagent.policy.engine import ProposedAction, evaluate

    snap = build_snapshot(raw([
        el("/c[1]", "combobox", "Application type", tag="cfc-select"),
        el("/o[1]", "option", "Web application", tag="div"),
    ]), Masker())
    assert [(e.role, e.name) for e in snap.elements] == [("combobox", "Application type"), ("option", "Web application")]
    pick = ProposedAction("click", "/x", "option 'Web application'")
    assert evaluate(pick, snap.obs, [], ["127.0.0.1"], risk="reversible", risk_uncertain=False).decision == "DECIDE"
    open_it = ProposedAction("click", "/x", "combobox 'Application type'")
    assert evaluate(open_it, snap.obs, [], ["127.0.0.1"], risk="reversible", risk_uncertain=False).decision == "allow"


def test_google_consoles_auth_path_is_not_a_sign_in_page_but_real_sign_in_addresses_are_d098():
    from credagent.agent.loop import AgentLoop

    def is_signin(url):
        return AgentLoop._looks_like_signin(snap(url=url))

    assert not is_signin("https://console.cloud.google.com/projectselector2/auth/clients?pli=1")
    assert not is_signin("https://app.slack.com/app-settings/T1/A1/general")
    assert is_signin("https://accounts.google.com/v3/signin/identifier?continue=x")
    assert is_signin("https://slack.com/signin?entry_point=redirect_flow")
    assert is_signin("https://discord.com/login")
