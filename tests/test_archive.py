from rpg_chronicler import archive, cli
from rpg_chronicler.session import list_sessions


def test_belongs_to_does_not_take_other_sessions_files():
    assert archive.belongs_to("Fallout_1.txt", "Fallout_1", False)
    assert archive.belongs_to("Fallout_1.mowcy.json", "Fallout_1", False)
    assert archive.belongs_to("Fallout_1_podsumowanie.txt", "Fallout_1", True)
    assert archive.belongs_to("Fallout_1_kronika.pdf", "Fallout_1", True)
    assert not archive.belongs_to("Fallout_1_cz2_podsumowanie.txt", "Fallout_1", True)  # inna sesja
    assert not archive.belongs_to("BEZ_Fallout_1.txt", "Fallout_1", False)
    assert not archive.belongs_to("Fallout_10.txt", "Fallout_1", False)
    assert not archive.belongs_to("Fallout_1_podsumowanie.txt", "Fallout_1", False)  # poza folderem kronik


def test_archive_moves_all_files_and_hides_session(workspace):
    workspace.add_transcript("OLD_Fallout_1", "[0.00s -> 1.00s] a\n")
    workspace.add_transcript("Fallout_1", "[0.00s -> 1.00s] b\n")
    workspace.add_audio("OLD_Fallout_1")
    (workspace.dirs["txt"] / "OLD_Fallout_1.mowcy.json").write_text("{}", encoding="utf-8")
    (workspace.dirs["summary"] / "OLD_Fallout_1_podsumowanie.txt").write_text("K", encoding="utf-8")

    assert cli.main(["archive", "OLD_Fallout_1", "--offline", "--dry-run"]) == 0
    assert [s.name for s in list_sessions()] == ["Fallout_1", "OLD_Fallout_1"]

    assert cli.main(["archive", "OLD_Fallout_1", "--offline"]) == 0
    assert [s.name for s in list_sessions()] == ["Fallout_1"]
    for key, name in (("txt", "OLD_Fallout_1.txt"), ("txt", "OLD_Fallout_1.mowcy.json"),
                      ("audio", "OLD_Fallout_1.m4a"), ("summary", "OLD_Fallout_1_podsumowanie.txt")):
        assert (workspace.dirs[key] / "archiwum" / name).exists()
        assert not (workspace.dirs[key] / name).exists()


def test_archive_refuses_to_overwrite(workspace, capsys):
    workspace.add_transcript("X_1", "[0.00s -> 1.00s] a\n")
    (workspace.dirs["txt"] / "archiwum").mkdir()
    (workspace.dirs["txt"] / "archiwum" / "X_1.txt").write_text("stare", encoding="utf-8")
    assert cli.main(["archive", "X_1", "--offline"]) == 1
    assert "już pliki" in capsys.readouterr().out
    assert (workspace.dirs["txt"] / "X_1.txt").exists()


def test_remote_files_skip_subfolders():
    listing = ["X_1.txt", "archiwum/X_1.txt", "X_1_podsumowanie.txt", "Y_1.txt"]
    assert archive.remote_files(listing, "X_1", True) == ["X_1.txt", "X_1_podsumowanie.txt"]
