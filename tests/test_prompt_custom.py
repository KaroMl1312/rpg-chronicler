"""Prompty zmieniane przez użytkownika (okno „Prompty AI”)."""
import json

import pytest

from rpg_chronicler.prompts import CACHE_MARK, catalog, custom, render, render_split
from rpg_chronicler.web import prompts_api


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_CHRONICLER_SETTINGS", str(tmp_path / "ustawienia.toml"))
    return tmp_path / "prompty"


def test_every_prompt_is_described_and_survives_editing_unchanged():
    assert len(custom.names()) >= 18
    for name in custom.names():
        base = custom.default(name)
        assert custom.to_template(custom.to_display(base), custom.fields(base)) == base, name
        assert name in catalog.PROMPTS and catalog.info(name)[0] in catalog.GROUPS
        assert all(field in catalog.FIELDS for field in custom.fields(base)), name
        assert custom.warnings(name, custom.to_display(base)) == [], name


def test_user_sees_single_braces_and_json_stays_literal(folder):
    text = 'Kronika {system_name}. Odpowiedz JSON: {"nazwa": "…", "sesje": []} i {zle}.'
    warnings = custom.save("teaser", text)
    assert "{{\"nazwa\"" in (folder / "teaser.md").read_text(encoding="utf-8")
    assert render("teaser", system_name="Warhammer", chronicle="x") == \
        'Kronika Warhammer. Odpowiedz JSON: {"nazwa": "…", "sesje": []} i {zle}.'
    assert any("{chronicle}" in w for w in warnings) and any("{zle}" in w for w in warnings)


def test_same_as_default_removes_change_and_reset(folder):
    custom.save("brief", "Krótko: {system_name}")
    assert custom.status("brief") == {"changed": True, "default_updated": False}
    custom.save("brief", custom.to_display(custom.default("brief")))
    assert not (folder / "brief.md").exists() and not custom.status("brief")["changed"]
    custom.save("brief", "Inaczej {system_name}")
    custom.reset("brief")
    assert custom.template("brief") == custom.default("brief") and not (folder / "brief.md").exists()
    assert "brief" not in json.loads((folder / custom.META_FILE).read_text(encoding="utf-8"))


def test_errors(folder):
    with pytest.raises(custom.PromptError):
        custom.save("brief", "  \n")
    for name in ("nie_ma", "../summary", "summary.md"):
        with pytest.raises(custom.PromptError):
            custom.save(name, "x")


def test_broken_file_falls_back_to_default(folder, capsys):
    folder.mkdir()
    (folder / "brief.md").write_text("Zepsuty {", encoding="utf-8")
    assert custom.template("brief") == custom.default("brief")
    assert "uszkodzony" in capsys.readouterr().out


def test_default_changed_in_new_version(folder):
    custom.save("brief", "Moja wersja {system_name}")
    meta = folder / custom.META_FILE
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["brief"]["base"] = "starszy"
    meta.write_text(json.dumps(data), encoding="utf-8")
    assert custom.status("brief") == {"changed": True, "default_updated": True}


def test_cache_mark_is_kept_and_its_absence_reported(folder):
    base = custom.to_display(custom.default("events"))
    assert CACHE_MARK in base
    custom.save("events", "NA POCZĄTKU\n" + base)
    values = {f: "x" for f in custom.fields(custom.default("events"))}
    head, tail = render_split("events", **values)
    assert head.startswith("NA POCZĄTKU") and tail
    warnings = custom.save("events", base.replace(f"\n{CACHE_MARK}\n", "\n"))
    assert any(CACHE_MARK in w for w in warnings)


def test_window_api(folder):
    listing = prompts_api.prompt_list()
    assert [x["group"] for x in listing["items"]][0] == "Kronika"
    detail = prompts_api.prompt("quotes")
    assert detail["text"] == detail["default"] and not detail["changed"] and detail["fields"]
    saved = prompts_api.save("quotes", detail["text"] + "\nDodatkowo: krótko.")
    assert saved["changed"] and saved["text"].endswith("krótko.") and saved["warnings"] == []
    assert next(x for x in prompts_api.prompt_list()["items"] if x["name"] == "quotes")["changed"]
    assert not prompts_api.reset("quotes")["changed"]
    with pytest.raises(ValueError):
        prompts_api.prompt("nie_ma")
