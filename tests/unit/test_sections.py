from credagent.research.sections import OMITTED, select, split_sections


def page(n_filler=30):
    secs = ["# Intro\nThis page explains apps."]
    secs += [f"## Filler {i}\n" + ("Lorem ipsum dolor sit amet. " * 20) for i in range(n_filler)]
    secs.insert(15, "## Generate a client secret\nClick Generate a new client secret. The client secret "
                    "is shown once. Copy the client ID too.")
    secs.append("## Terms\nBy clicking Register you agree to the terms.")
    return "\n\n".join(secs)


def test_short_page_is_complete():
    sel = select("short page", 1000)
    assert sel.complete and sel.text == "short page" and sel.chars_seen == sel.chars_total


def test_long_page_keeps_intro_and_relevant_sections_in_order():
    text = page()
    sel = select(text, 2000)
    assert not sel.complete and sel.chars_seen <= 2000 < sel.chars_total
    assert sel.text.startswith("# Intro")
    assert "Generate a client secret" in sel.text and "you agree to the terms" in sel.text
    assert sel.text.index("Generate a client secret") < sel.text.index("you agree to the terms")
    assert OMITTED.strip() in sel.text
    assert 2 < sel.kept < sel.total


def test_deterministic_and_app_terms_boost():
    text = page()
    assert select(text, 2000) == select(text, 2000)
    boosted = select(text.replace("Filler 3\n", "Filler 3\nAcmeWidget AcmeWidget AcmeWidget "), 2000,
                     ("AcmeWidget",))
    assert "AcmeWidget" in boosted.text


def test_split_without_headings_uses_paragraphs_and_caps_size():
    secs = split_sections(("para one " * 50) + "\n\n" + ("x" * 6000))
    assert len(secs) >= 3 and all(len(s) <= 2500 for s in secs)
