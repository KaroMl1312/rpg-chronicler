"""Dwukierunkowa synchronizacja danych kampanii: zmiany, usunięcia, konflikty, bezpiecznik, rclone."""
import shutil

import pytest

from rpg_chronicler.storage import campaign_sync as cs


@pytest.fixture
def sides(tmp_path, monkeypatch):
    """Dwa komputery (a, b) i „Drive” jako zwykły folder; stan synchronizacji osobno dla każdego komputera."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    drive = tmp_path / "drive"
    drive.mkdir()
    roots = {name: tmp_path / name for name in ("a", "b")}
    for root in roots.values():
        root.mkdir()

    def sync(name, **kwargs):
        return cs.CampaignSync(roots[name], cs.FolderRemote(drive)).run(**kwargs)

    return roots, drive, sync


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def test_only_campaign_data_is_synced():
    for rel in ("kampanie.toml", "kampanie/Warhammer/plany/Warhammer_261204.md", "obrazy/Warhammer/fen.jpg"):
        assert cs.is_synced(rel), rel
    for rel in ("Warhammer_261126.txt", "kampanie/.ukryty.md", "kampanie/x.md.part", "archiwum/kampanie.toml",
                "obrazy.jpg", "stan-kampanii-Warhammer.md"):
        assert not cs.is_synced(rel), rel


def test_changes_travel_between_computers(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie.toml", "[Warhammer]\n")
    write(a, "kampanie/Warhammer/plany/sesja.md", "plan")
    write(a, "Warhammer_261126.txt", "transkrypcja - nie należy do tej synchronizacji")
    assert sync("a").uploaded == ["kampanie.toml", "kampanie/Warhammer/plany/sesja.md"]
    assert not (drive / "Warhammer_261126.txt").exists()

    assert sorted(sync("b").downloaded) == ["kampanie.toml", "kampanie/Warhammer/plany/sesja.md"]
    write(b, "kampanie/Warhammer/plany/sesja.md", "plan poprawiony na laptopie")
    assert sync("b").uploaded == ["kampanie/Warhammer/plany/sesja.md"]
    assert sync("a").downloaded == ["kampanie/Warhammer/plany/sesja.md"]
    assert read(a, "kampanie/Warhammer/plany/sesja.md") == "plan poprawiony na laptopie"
    report = sync("a")
    assert not report.changed and report.summary() == "bez zmian"


def test_deletions_travel_and_go_to_trash(sides, tmp_path):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "obrazy/Warhammer/fen.jpg", "zdjęcie")
    sync("a"), sync("b")
    (b / "obrazy/Warhammer/fen.jpg").unlink()
    assert sync("b").deleted_remote == ["obrazy/Warhammer/fen.jpg"]
    assert sync("a").deleted_local == ["obrazy/Warhammer/fen.jpg"]
    assert not (a / "obrazy/Warhammer/fen.jpg").exists()
    assert list((tmp_path / "data/rpg-chronicler/kosz-synchronizacji").rglob("fen.jpg"))


def test_change_wins_over_deletion(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie/Warhammer/karty/goblin.md", "PŻ 5")
    sync("a"), sync("b")
    (a / "kampanie/Warhammer/karty/goblin.md").unlink()
    write(b, "kampanie/Warhammer/karty/goblin.md", "PŻ 7")
    sync("b")
    assert sync("a").downloaded == ["kampanie/Warhammer/karty/goblin.md"]
    assert read(a, "kampanie/Warhammer/karty/goblin.md") == "PŻ 7"


def test_conflict_keeps_both_versions_until_resolved(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie.toml", "wersja 0")
    sync("a"), sync("b")
    write(a, "kampanie.toml", "zmiana na komputerze")
    write(b, "kampanie.toml", "zmiana na laptopie")
    sync("b")
    report = sync("a")
    assert report.conflicts == ["kampanie.toml"] and report.pending == ["kampanie.toml"]
    assert read(a, "kampanie.toml") == "zmiana na komputerze"         # nic nie nadpisane
    assert read(drive, "kampanie.toml") == "zmiana na laptopie"
    assert not sync("a").conflicts and sync("a").pending == ["kampanie.toml"]   # czeka, nie zgłasza drugi raz

    engine = cs.CampaignSync(a, cs.FolderRemote(drive))
    details = engine.conflict("kampanie.toml")
    assert details["text"] and details["remote"].read_text(encoding="utf-8") == "zmiana na laptopie"
    engine.resolve("kampanie.toml", "remote")
    assert read(a, "kampanie.toml") == "zmiana na laptopie" and engine.pending == []
    assert not sync("a").changed and not sync("b").changed


def test_resolve_local_and_both(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    for rel in ("kampanie/W/x.md", "kampanie/W/y.md"):
        write(a, rel, "0")
    sync("a"), sync("b")
    for rel in ("kampanie/W/x.md", "kampanie/W/y.md"):
        write(a, rel, "a")
        write(b, rel, "b")
    sync("b"), sync("a")
    engine = cs.CampaignSync(a, cs.FolderRemote(drive))
    assert engine.pending == ["kampanie/W/x.md", "kampanie/W/y.md"]
    engine.resolve("kampanie/W/x.md", "local")
    assert read(drive, "kampanie/W/x.md") == "a"
    extra = engine.resolve("kampanie/W/y.md", "both")
    assert extra.startswith("kampanie/W/y (z Drive ") and read(a, extra) == "b" and read(drive, extra) == "b"
    assert read(a, "kampanie/W/y.md") == "a" == read(drive, "kampanie/W/y.md")
    sync("b")
    assert read(b, "kampanie/W/x.md") == "a" and read(b, extra) == "b"
    with pytest.raises(cs.SyncError):
        engine.resolve("kampanie/W/x.md", "local")   # już rozstrzygnięty


def test_same_change_on_both_sides_is_not_a_conflict(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie.toml", "0")
    sync("a"), sync("b")
    write(a, "kampanie.toml", "1")
    write(b, "kampanie.toml", "1")
    sync("a")
    assert not sync("b").conflicts


def test_guard_against_mass_deletion(sides):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    for i in range(6):
        write(a, f"kampanie/W/{i}.md", str(i))
    sync("a")
    shutil.rmtree(drive / "kampanie")       # np. folder przeniesiony na Drive
    with pytest.raises(cs.SyncError, match="usunęłaby 6 z 6"):
        sync("a")
    assert len(list((a / "kampanie/W").iterdir())) == 6
    assert sync("a", dry_run=True).deleted_local and len(list((a / "kampanie/W").iterdir())) == 6
    assert len(sync("a", force=True).deleted_local) == 6


def test_offline_changes_nothing_and_lock(sides, tmp_path):
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie.toml", "0")
    with pytest.raises(cs.SyncError):
        cs.CampaignSync(a, cs.FolderRemote(tmp_path / "nie-ma")).run()
    engine = cs.CampaignSync(a, cs.FolderRemote(drive))
    engine._lock()
    with pytest.raises(cs.SyncError, match="już trwa"):
        cs.CampaignSync(a, cs.FolderRemote(drive)).run()
    engine._unlock()
    assert sync("a").uploaded == ["kampanie.toml"]


@pytest.mark.skipif(not shutil.which("rclone"), reason="brak rclone")
def test_real_rclone_commands_on_local_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    drive, a, b = tmp_path / "drive", tmp_path / "a", tmp_path / "b"
    for root in (drive, a, b):
        root.mkdir()
    write(a, "kampanie.toml", "toml")
    write(a, "obrazy/Warhammer/piętaszek.jpg", "zdjęcie")
    write(a, "Warhammer_261126.txt", "poza synchronizacją")
    assert len(cs.CampaignSync(a, cs.RcloneRemote(str(drive))).run().uploaded) == 2
    assert not (drive / "Warhammer_261126.txt").exists()
    assert len(cs.CampaignSync(b, cs.RcloneRemote(str(drive))).run().downloaded) == 2
    write(a, "kampanie.toml", "z a")
    write(b, "kampanie.toml", "z b")
    cs.CampaignSync(b, cs.RcloneRemote(str(drive))).run()
    engine = cs.CampaignSync(a, cs.RcloneRemote(str(drive)))
    assert engine.run().conflicts == ["kampanie.toml"]
    engine.resolve("kampanie.toml", "local")
    assert read(drive, "kampanie.toml") == "z a"
    (a / "obrazy/Warhammer/piętaszek.jpg").unlink()
    assert engine.run().deleted_remote == ["obrazy/Warhammer/piętaszek.jpg"]
    assert not (drive / "obrazy/Warhammer/piętaszek.jpg").exists()


def test_window_sync_in_background(sides, monkeypatch):
    import time

    from rpg_chronicler.web import sync_api
    (a, b), drive, sync = sides[0].values(), sides[1], sides[2]
    write(a, "kampanie.toml", "0")
    sync("a"), sync("b")
    write(a, "kampanie.toml", "a")
    write(b, "kampanie.toml", "b")
    write(b, "obrazy/W/fen.png", "png")
    sync("b")
    monkeypatch.setattr(sync_api, "engine", lambda: cs.CampaignSync(a, cs.FolderRemote(drive)))
    monkeypatch.setattr(cs, "remote_configured", lambda remote=None: True)
    seq = sync_api.status()["seq"]
    sync_api.start()
    end = time.monotonic() + 10
    while sync_api.status()["seq"] == seq and time.monotonic() < end:
        time.sleep(0.05)
    status = sync_api.status()
    assert not status["running"] and status["result"]["downloaded"] == ["obrazy/W/fen.png"]
    assert status["pending"] == ["kampanie.toml"]
    detail = sync_api.conflict("kampanie.toml")
    assert detail["local"]["text"] == "a" and detail["remote"]["text"] == "b"
    assert sync_api.resolve("kampanie.toml", "local")["pending"] == []
    monkeypatch.setattr(cs, "remote_configured", lambda remote=None: False)
    assert "rclone" in sync_api.start()["error"]
