import os
import subprocess
import sys

import pytest

from rpg_chronicler import doctor

# ./sprawdz-srodowisko naprawia .venv linuksowe (bin/python, python3.11 z systemu)
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="sprawdz-srodowisko działa tylko na Linuksie")


def fake_venv(tmp_path, monkeypatch, python_target="/usr/bin/python3.9-nie-ma"):
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    os.symlink(python_target, venv / "bin" / "python")
    monkeypatch.setattr(doctor, "VENV", venv)
    monkeypatch.setattr(doctor, "VENV_PYTHON", venv / "bin" / "python")
    return venv


def test_broken_venv_after_system_upgrade_is_reported(tmp_path, monkeypatch, capsys):
    fake_venv(tmp_path, monkeypatch)
    report = doctor.Report()
    doctor.check_venv(report)
    assert report.errors == 1
    out = capsys.readouterr().out
    assert "brak interpretera /usr/bin/python3.9-nie-ma" in out and "--napraw" in out


def test_failed_repair_restores_previous_venv(tmp_path, monkeypatch):
    venv = fake_venv(tmp_path, monkeypatch)
    (venv / "znacznik").write_text("stare", encoding="utf-8")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/python3.11")

    def run(cmd, **kwargs):
        if "venv" in cmd:  # tworzenie nowego .venv się udaje, instalacja pip już nie
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(doctor.subprocess, "run", run)
    assert doctor.repair_venv() == 1
    assert (venv / "znacznik").read_text(encoding="utf-8") == "stare"
    assert not venv.with_name(".venv.stare").exists()


def test_repair_installs_cpu_torch_before_project(tmp_path, monkeypatch):
    fake_venv(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/python3.11")
    commands = []
    monkeypatch.setattr(doctor.subprocess, "run",
                        lambda cmd, **kw: commands.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    assert doctor.repair_venv() == 0
    torch_step = next(i for i, c in enumerate(commands) if "torch" in c)
    project_step = next(i for i, c in enumerate(commands) if "-e" in c)
    assert torch_step < project_step and doctor.TORCH_CPU_INDEX in commands[torch_step]
    assert not (tmp_path / ".venv.stare").exists()
