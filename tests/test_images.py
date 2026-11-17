"""Obrazki haseł od AI (images.py): Cloudflare FLUX (bez sieci), styl kampanii, propozycja → zdjęcie."""
import base64
import io
import json
import os
import urllib.error

import pytest

from rpg_chronicler import campaigns, cli, config
from rpg_chronicler.campaign_tools import images
from rpg_chronicler.campaigns import Campaign, load_campaigns

CAMPAIGN = Campaign("Warhammer", "Warhammer Fantasy", context="Reikland, rok 2512.",
                    player_characters={"Sir Amos": ""}, glossary={"miejsca": ("Ubersreik",)},
                    descriptions={"Sir Amos": "Niziołek-rycerz z łukiem."})


class FakeImages:
    name = "Fake FLUX"

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return b"JPEG" + str(len(self.prompts)).encode()


@pytest.fixture
def campaign_store(workspace, monkeypatch):
    monkeypatch.setattr(config, "TXT_DIR", str(workspace.dirs["txt"]))
    store = {"Warhammer": CAMPAIGN}
    monkeypatch.setattr(campaigns, "load_campaigns", lambda path=None: store)
    monkeypatch.setattr(campaigns, "update_campaign", lambda c, path=None: store.update({c.key: c}))
    monkeypatch.setattr(images, "update_campaign", lambda c, path=None: store.update({c.key: c}))
    answers = iter(["grimdark fantasy, ink and watercolor, muted palette", "A halfling knight with a bow, "
                    "grimdark fantasy, ink and watercolor, full-bleed image filling the entire frame, unsigned"] * 5)
    workspace.llm.generate = lambda prompt: workspace.llm.prompts.append(prompt) or next(answers)
    return store


def test_category_and_style_roundtrip(tmp_path):
    assert CAMPAIGN.category_of("sir amos") == "postacie_graczy" and CAMPAIGN.category_of("Ubersreik") == "miejsca"
    assert CAMPAIGN.category_of("Nikt") is None
    path = str(tmp_path / "kampanie.toml")
    from dataclasses import replace
    campaigns.save_campaigns({"Warhammer": replace(CAMPAIGN, image_style="ink, muted")}, path)
    assert load_campaigns(path)["Warhammer"].image_style == "ink, muted"


def test_cloudflare_client(monkeypatch):
    with pytest.raises(images.ImageError, match="CLOUDFLARE"):
        images.CloudflareImages(account_id="", token="")
    sent = {}

    def ok(request, timeout):
        sent.update(url=request.full_url, body=json.loads(request.data), auth=request.get_header("Authorization"))
        return io.BytesIO(json.dumps({"result": {"image": base64.b64encode(b"jpg").decode()}}).encode())

    monkeypatch.setattr(images.urllib.request, "urlopen", ok)
    client = images.CloudflareImages(account_id="abc", token="t0k")
    assert client.generate("a knight") == b"jpg"
    assert sent["url"].endswith("/accounts/abc/ai/run/@cf/black-forest-labs/flux-1-schnell")
    assert sent["body"] == {"prompt": "a knight", "steps": config.IMAGE_STEPS} and sent["auth"] == "Bearer t0k"

    def limit(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {},
                                     io.BytesIO(b'{"errors": [{"message": "daily limit"}]}'))

    monkeypatch.setattr(images.urllib.request, "urlopen", limit)
    with pytest.raises(images.ImageError, match="limit darmowych obrazków") as error:
        client.generate("a knight")
    assert error.value.retryable


def test_candidate_style_and_keep(campaign_store, workspace):
    fake = FakeImages()
    path = images.generate_candidate(workspace.llm, fake, CAMPAIGN, "Sir Amos")
    assert campaign_store["Warhammer"].image_style == "grimdark fantasy, ink and watercolor, muted palette"
    style_prompt, image_prompt = workspace.llm.prompts
    assert "Warhammer Fantasy" in style_prompt and "{" not in style_prompt
    assert "Sir Amos (postać gracza)" in image_prompt and "Niziołek-rycerz z łukiem." in image_prompt
    assert "grimdark fantasy, ink and watercolor, muted palette" in image_prompt
    assert fake.prompts[0].endswith("unsigned") and images.candidate("Warhammer", "Sir Amos") == path
    assert images.prompt_for("Warhammer", "Sir Amos") == fake.prompts[0]

    images.generate_candidate(workspace.llm, fake, campaign_store["Warhammer"], "Sir Amos")   # styl już jest
    assert len(workspace.llm.prompts) == 3
    saved = images.keep_candidate("Warhammer", "Sir Amos")
    assert open(saved, "rb").read() == b"JPEG2" and saved == campaigns.image_path("Warhammer", "Sir Amos")
    assert images.candidate("Warhammer", "Sir Amos") is None and not list(images.candidates_dir("Warhammer").iterdir())
    with pytest.raises(images.ImageError):
        images.generate_candidate(workspace.llm, fake, CAMPAIGN, "Nikt")


def test_image_command(campaign_store, workspace, monkeypatch, capsys):
    monkeypatch.setattr(images, "get_image_client", FakeImages)
    assert cli.main(["image", "Warhammer", "ubersreik"]) == 0
    assert "Propozycja obrazka „Ubersreik”" in capsys.readouterr().out
    assert images.candidate("Warhammer", "Ubersreik") is not None
    assert cli.main(["image", "Warhammer", "Ubersreik", "--zachowaj"]) == 0
    assert os.path.exists(campaigns.image_path("Warhammer", "Ubersreik"))
    monkeypatch.setattr(images, "get_image_client", lambda: (_ for _ in ()).throw(images.ImageError("brak kluczy")))
    assert cli.main(["image", "Warhammer", "Ubersreik"]) == 1
    assert "brak kluczy" in capsys.readouterr().err


def test_user_hints_translated_in_prompt(campaign_store, workspace, monkeypatch, capsys):
    fake = FakeImages()
    images.generate_candidate(workspace.llm, fake, CAMPAIGN, "Sir Amos", "  rude włosy,\n blizna na policzku ")
    image_prompt = workspace.llm.prompts[-1]
    assert "Wskazówki użytkownika (najważniejsze): rude włosy, blizna na policzku" in image_prompt
    assert "przetłumacz je na angielski" in image_prompt
    assert images.last_hints("Warhammer", "Sir Amos") == "rude włosy,\n blizna na policzku"
    images.discard_candidates("Warhammer", "Sir Amos")
    assert images.last_hints("Warhammer", "Sir Amos")                     # odrzucenie obrazka zostawia wskazówki
    images.generate_candidate(workspace.llm, fake, campaign_store["Warhammer"], "Sir Amos")
    assert "Wskazówki użytkownika (najważniejsze)" not in workspace.llm.prompts[-1]
    assert images.last_hints("Warhammer", "Sir Amos") == ""

    monkeypatch.setattr(images, "get_image_client", FakeImages)
    assert cli.main(["image", "Warhammer", "Sir Amos", "--wskazowki", "w deszczu"]) == 0
    assert "Wskazówki użytkownika (najważniejsze): w deszczu" in workspace.llm.prompts[-1]
    assert "(wskazówki: w deszczu)" in capsys.readouterr().out
