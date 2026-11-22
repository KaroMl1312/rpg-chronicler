import os
import stat

from rpg_chronicler import envfile


def test_update_creates_private_file_and_updates_environ(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    envfile.update({"GEMINI_API_KEY": ' "abc" \n'}, path)
    assert envfile.read(path) == {"GEMINI_API_KEY": "abc"}
    assert path.read_text(encoding="utf-8").startswith("# Klucze API")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.environ["GEMINI_API_KEY"] == "abc"

    envfile.update({"GEMINI_API_KEY": ""}, path)
    assert "GEMINI_API_KEY" not in os.environ
    assert envfile.read(path) == {"GEMINI_API_KEY": ""}


def test_update_keeps_other_lines_and_comments(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# komentarz\nLLM_PROVIDER=gemini\nHUGGINGFACE_TOKEN=stary\n\nHUGGINGFACE_TOKEN=duplikat\n",
                    encoding="utf-8")
    monkeypatch.setenv("HUGGINGFACE_TOKEN", "stary")
    envfile.update({"HUGGINGFACE_TOKEN": "hf_nowy", "CLOUDFLARE_ACCOUNT_ID": "123"}, path)
    assert path.read_text(encoding="utf-8") == ("# komentarz\nLLM_PROVIDER=gemini\nHUGGINGFACE_TOKEN=hf_nowy\n\n"
                                                "CLOUDFLARE_ACCOUNT_ID=123\n")
    assert os.environ["HUGGINGFACE_TOKEN"] == "hf_nowy"
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID")


def test_load_does_not_override_shell_variables(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY='z-pliku'\nANTHROPIC_API_KEY=\"sk-ant-x\"\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "z-powloki")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    envfile.load_into_environ(path)
    assert os.environ["GEMINI_API_KEY"] == "z-powloki"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-x"
    monkeypatch.delenv("ANTHROPIC_API_KEY")


def test_every_service_has_https_links():
    names = [key.name for service in envfile.SERVICES for key in service.keys]
    assert names == ["HUGGINGFACE_TOKEN", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "CLOUDFLARE_ACCOUNT_ID",
                     "CLOUDFLARE_API_TOKEN"]
    assert all(url.startswith("https://") for service in envfile.SERVICES for _t, _h, url in service.links)
