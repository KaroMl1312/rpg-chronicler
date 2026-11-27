"""Dwukierunkowa synchronizacja danych kampanii z Google Drive, z wykrywaniem konfliktów.

Dane kampanii (przygotowania) edytuje się na kilku komputerach, więc zwykłe `rclone copy --update` (nowszy plik
wygrywa) gubiłoby zmiany. Tu program pamięta (lokalnie, osobno na każdym komputerze) sumę MD5 każdego pliku
z ostatniej synchronizacji i dla każdego pliku porównuje: zmiana tylko po jednej stronie → kopiuje ją na drugą,
usunięcie po jednej stronie → usuwa po drugiej (Drive: do kosza, lokalnie: do kosza aplikacji), zmiana po obu
stronach → konflikt do rozstrzygnięcia (obie wersje zostają; zmiana wygrywa z usunięciem). Bezpiecznik: gdy
synchronizacja miałaby usunąć ponad połowę znanych plików, przerywa (np. zmieniony folder na Drive).

Synchronizowane ścieżki (`SYNCED`) są wyłączone ze zwykłego `sync`/`upload` (storage/drive.py). Tylko stdlib + rclone.
"""
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import session as _session
from ..config import IS_WINDOWS, RCLONE_TXT_REMOTE

# względem folderu transkrypcji (lokalnie) i RCLONE_TXT_REMOTE (Drive)
SYNCED_FILES = ("kampanie.toml",)
SYNCED_DIRS = ("kampanie", "obrazy")
MAX_DELETE_FRACTION = 0.5
MIN_GUARDED_DELETES = 4      # pojedyncze usunięcia nie uruchamiają bezpiecznika
LOCK_STALE_SECONDS = 15 * 60
RCLONE_NET = ("--contimeout", "15s", "--timeout", "60s", "--retries", "2", "--low-level-retries", "3")
TEXT_EXTENSIONS = {".md", ".toml", ".txt", ".json", ".csv"}


class SyncError(RuntimeError):
    pass


def is_synced(path: str) -> bool:
    """Czy ścieżka (względna, z „/”) należy do danych kampanii; bez plików ukrytych i tymczasowych."""
    parts = path.split("/")
    if any(p.startswith(".") for p in parts) or path.endswith((".part", ".partial")):
        return False
    return path in SYNCED_FILES or (len(parts) > 1 and parts[0] in SYNCED_DIRS)


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "rpg-chronicler"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "rpg-chronicler"


# --- strony synchronizacji ---

class LocalSide:
    """Folder transkrypcji na tym komputerze; MD5 liczone tylko dla plików zmienionych od ostatniego razu."""

    def __init__(self, root: Path, hash_cache: dict):
        self.root = Path(root)
        self.hash_cache = hash_cache     # ścieżka -> [rozmiar, mtime_ns, md5]

    def listing(self) -> dict[str, str]:
        found = {}
        candidates = [self.root / name for name in SYNCED_FILES]
        for folder in SYNCED_DIRS:
            if (self.root / folder).is_dir():
                candidates += [p for p in (self.root / folder).rglob("*") if p.is_file()]
        for path in candidates:
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if not is_synced(rel):
                continue
            stat = path.stat()
            cached = self.hash_cache.get(rel)
            if cached and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
                found[rel] = cached[2]
            else:
                found[rel] = md5_of(path)
                self.hash_cache[rel] = [stat.st_size, stat.st_mtime_ns, found[rel]]
        for rel in list(self.hash_cache):
            if rel not in found:
                del self.hash_cache[rel]
        return found

    def path(self, rel: str) -> Path:
        return self.root / Path(rel)


class RcloneRemote:
    """Folder na Google Drive (albo innym zdalnym miejscu rclone)."""

    def __init__(self, root: str):
        self.root = root.rstrip("/")

    def _run(self, args: list[str], what: str) -> subprocess.CompletedProcess:
        try:
            proc = subprocess.run(["rclone", *args, *RCLONE_NET], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
        except FileNotFoundError:
            raise SyncError("Brak programu rclone.") from None
        if proc.returncode != 0:
            lines = [line for line in proc.stderr.splitlines() if line.strip()]
            raise SyncError(f"{what}: {lines[-1] if lines else f'kod {proc.returncode}'}")
        return proc

    def listing(self) -> dict[str, str]:
        filters = [arg for name in SYNCED_FILES for arg in ("--include", f"/{name}")]
        filters += [arg for name in SYNCED_DIRS for arg in ("--include", f"/{name}/**")]
        proc = self._run(["lsjson", self.root, "--recursive", "--files-only", "--hash", "--hash-type", "md5",
                          *filters], "Nie udało się odczytać plików z Google Drive")
        items = json.loads(proc.stdout or "[]")
        return {item["Path"]: (item.get("Hashes") or {}).get("md5", "") for item in items if is_synced(item["Path"])}

    def _with_list(self, paths: list[str], args: list[str], what: str) -> None:
        if not paths:
            return
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
            f.write("\n".join(paths) + "\n")
        try:
            self._run([*args[:1], "--files-from-raw", f.name, *args[1:]], what)
        finally:
            os.unlink(f.name)

    def download(self, paths: list[str], local_root: Path) -> None:
        self._with_list(paths, ["copy", self.root, str(local_root), "--checksum"], "Nie udało się pobrać plików")

    def upload(self, paths: list[str], local_root: Path) -> None:
        self._with_list(paths, ["copy", str(local_root), self.root, "--checksum"], "Nie udało się wysłać plików")

    def delete(self, paths: list[str]) -> None:
        self._with_list(paths, ["delete", self.root], "Nie udało się usunąć plików na Google Drive")

    def fetch(self, rel: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        self._run(["copyto", f"{self.root}/{rel}", str(target)], "Nie udało się pobrać wersji z Google Drive")


class FolderRemote:
    """Zwykły folder jako „Drive” - do testów (i synchronizacji przez dysk sieciowy)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def listing(self) -> dict[str, str]:
        if not self.root.exists():
            raise SyncError(f"Brak folderu {self.root}")
        return LocalSide(self.root, {}).listing()

    def download(self, paths, local_root):
        for rel in paths:
            _copy(self.root / rel, Path(local_root) / rel)

    def upload(self, paths, local_root):
        for rel in paths:
            _copy(Path(local_root) / rel, self.root / rel)

    def delete(self, paths):
        for rel in paths:
            (self.root / rel).unlink(missing_ok=True)

    def fetch(self, rel, target):
        _copy(self.root / rel, Path(target))


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.part")
    shutil.copy2(source, tmp)
    os.replace(tmp, target)


# --- stan i blokada ---

@dataclass
class Report:
    uploaded: list[str] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)
    deleted_remote: list[str] = field(default_factory=list)
    deleted_local: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)        # nowe konflikty z tej synchronizacji
    pending: list[str] = field(default_factory=list)          # wszystkie nierozstrzygnięte

    @property
    def changed(self) -> bool:
        return bool(self.uploaded or self.downloaded or self.deleted_remote or self.deleted_local or self.conflicts)

    def summary(self) -> str:
        parts = [f"{label} {len(items)}" for label, items in (
            ("wysłano", self.uploaded), ("pobrano", self.downloaded), ("usunięto na Drive", self.deleted_remote),
            ("usunięto lokalnie", self.deleted_local), ("nowe konflikty", self.conflicts)) if items]
        return ", ".join(parts) or "bez zmian"

    def to_dict(self) -> dict:
        return {"uploaded": self.uploaded, "downloaded": self.downloaded, "deleted_remote": self.deleted_remote,
                "deleted_local": self.deleted_local, "conflicts": self.conflicts, "pending": self.pending,
                "summary": self.summary(), "changed": self.changed}


class CampaignSync:
    def __init__(self, local_root: Path | str | None = None, remote=None, remote_name: str | None = None):
        self.local_root = Path(local_root or _session.TXT_DIR)
        self.remote = remote or RcloneRemote(remote_name or RCLONE_TXT_REMOTE)
        key = hashlib.sha1(f"{self.local_root.resolve()}|{getattr(self.remote, 'root', '')}".encode()).hexdigest()[:12]
        self.state_path = data_dir() / "synchronizacja" / f"{key}.json"
        self.conflict_dir = cache_dir() / "konflikty" / key
        self.lock_path = self.state_path.with_suffix(".lock")
        self.state = self._load()

    # stan

    def _load(self) -> dict:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}
        for key in ("files", "hash_cache", "conflicts"):
            state.setdefault(key, {})
        return state

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    def _lock(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if time.time() - self.lock_path.stat().st_mtime > LOCK_STALE_SECONDS:
                self.lock_path.unlink(missing_ok=True)   # po awarii programu
        except FileNotFoundError:
            pass
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SyncError("Synchronizacja kampanii już trwa (w innym oknie albo zadaniu).") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)

    def _unlock(self) -> None:
        self.lock_path.unlink(missing_ok=True)

    @property
    def pending(self) -> list[str]:
        return sorted(self.state["conflicts"])

    @property
    def last_sync(self) -> str | None:
        return self.state.get("last_sync")

    # synchronizacja

    def plan(self, local: dict[str, str], remote: dict[str, str]) -> tuple[dict[str, list[str]], list[str]]:
        """Co zrobić z każdym plikiem: (akcje, nowe konflikty). Ścieżki w konflikcie czekają na rozstrzygnięcie."""
        base = self.state["files"]
        actions = {"upload": [], "download": [], "delete_remote": [], "delete_local": [], "same": []}
        conflicts = []
        for rel in sorted(set(local) | set(remote) | set(base)):
            mine, theirs, known = local.get(rel), remote.get(rel), base.get(rel)
            if rel in self.state["conflicts"]:
                if mine == theirs:   # rozstrzygnięte ręcznie poza programem
                    actions["same"].append(rel)
                continue
            if mine == theirs:
                actions["same"].append(rel)
                continue
            mine_changed, theirs_changed = mine != known, theirs != known
            if mine_changed and not theirs_changed:
                actions["upload" if mine else "delete_remote"].append(rel)
            elif theirs_changed and not mine_changed:
                actions["download" if theirs else "delete_local"].append(rel)
            elif mine is None:
                actions["download"].append(rel)     # zmiana na Drive wygrywa z usunięciem tutaj
            elif theirs is None:
                actions["upload"].append(rel)       # zmiana tutaj wygrywa z usunięciem na Drive
            else:
                conflicts.append(rel)
        return actions, conflicts

    def run(self, dry_run: bool = False, force: bool = False) -> Report:
        self._lock()
        try:
            return self._run(dry_run, force)
        finally:
            self._unlock()

    def _run(self, dry_run: bool, force: bool) -> Report:
        remote = self.remote.listing()   # bez sieci: SyncError i nic się nie zmienia
        side = LocalSide(self.local_root, self.state["hash_cache"])
        local = side.listing()
        actions, conflicts = self.plan(local, remote)
        deletes = len(actions["delete_remote"]) + len(actions["delete_local"])
        known = len(self.state["files"])
        if not (force or dry_run) and deletes >= MIN_GUARDED_DELETES and deletes > MAX_DELETE_FRACTION * known:
            raise SyncError(f"Synchronizacja usunęłaby {deletes} z {known} plików kampanii - przerwano dla "
                            "bezpieczeństwa (czy folder na Drive nie został zmieniony?). Sprawdź i uruchom z --force.")
        report = Report(uploaded=actions["upload"], downloaded=actions["download"],
                        deleted_remote=actions["delete_remote"], deleted_local=actions["delete_local"],
                        conflicts=conflicts)
        if dry_run:
            report.pending = sorted(set(self.pending) | set(conflicts))
            return report

        base = self.state["files"]
        for rel in actions["same"]:
            if local.get(rel):
                base[rel] = local[rel]
            else:
                base.pop(rel, None)
            self.state["conflicts"].pop(rel, None)
        self.remote.upload(actions["upload"], self.local_root)
        for rel in actions["upload"]:
            base[rel] = local[rel]
        self.remote.download(actions["download"], self.local_root)
        for rel in actions["download"]:
            base[rel] = remote[rel]
        self.remote.delete(actions["delete_remote"])
        for rel in actions["delete_remote"]:
            base.pop(rel, None)
        if actions["delete_local"]:
            trash = data_dir() / "kosz-synchronizacji" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            for rel in actions["delete_local"]:
                target = trash / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(side.path(rel)), str(target))
                base.pop(rel, None)
        for rel in conflicts:
            self.remote.fetch(rel, self.conflict_dir / rel)
            self.state["conflicts"][rel] = {"local": local[rel], "remote": remote[rel],
                                            "found": datetime.datetime.now().isoformat(timespec="seconds")}
        self.state["last_sync"] = datetime.datetime.now().isoformat(timespec="seconds")
        side.listing()   # pamięć MD5 po pobraniu plików
        self._save()
        report.pending = self.pending
        return report

    # konflikty

    def conflict(self, rel: str) -> dict:
        if rel not in self.state["conflicts"]:
            raise SyncError(f"Plik {rel} nie jest w konflikcie.")
        info = self.state["conflicts"][rel]
        local_path, remote_path = self.local_root / rel, self.conflict_dir / rel
        return {"path": rel, "found": info.get("found", ""), "text": Path(rel).suffix.lower() in TEXT_EXTENSIONS,
                "local": local_path if local_path.exists() else None,
                "remote": remote_path if remote_path.exists() else None}

    def resolve(self, rel: str, keep: str) -> str | None:
        """keep: "local" (moja wersja trafia na Drive), "remote" (wersja z Drive zastępuje moją), "both" (wersja
        z Drive zostaje obok jako osobny plik). Zwraca nazwę pliku z kopią przy "both"."""
        if keep not in ("local", "remote", "both"):
            raise SyncError(f"Nieznany wybór: {keep}")
        details = self.conflict(rel)
        local_path, remote_copy = self.local_root / rel, details["remote"]
        if remote_copy is None:
            remote_copy = self.conflict_dir / rel
            self.remote.fetch(rel, remote_copy)
        self._lock()
        try:
            extra = None
            if keep == "remote":
                _copy(remote_copy, local_path)
            else:
                if keep == "both":
                    stamp = datetime.date.today().isoformat()
                    sibling = local_path.with_name(f"{local_path.stem} (z Drive {stamp}){local_path.suffix}")
                    _copy(remote_copy, sibling)
                    extra = sibling.relative_to(self.local_root).as_posix()
                    if is_synced(extra):
                        self.remote.upload([extra], self.local_root)
                        self.state["files"][extra] = md5_of(sibling)
                if not local_path.exists():
                    raise SyncError(f"Nie ma lokalnego pliku {rel}.")
                self.remote.upload([rel], self.local_root)
            self.state["files"][rel] = md5_of(local_path)
            self.state["conflicts"].pop(rel, None)
            remote_copy.unlink(missing_ok=True)
            self._save()
            return extra
        finally:
            self._unlock()


def remote_configured(remote: str = RCLONE_TXT_REMOTE) -> bool:
    """Czy rclone jest zainstalowany i zna remote'a (np. gdrive:) - bez tego synchronizacja nie ma sensu."""
    if not shutil.which("rclone"):
        return False
    proc = subprocess.run(["rclone", "listremotes"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0)
    return proc.returncode == 0 and remote.split(":")[0] + ":" in proc.stdout.split()


def run_and_print(dry_run: bool = False, force: bool = False) -> Report | None:
    """Dla CLI (sync, upload, sync-campaigns): synchronizacja z komunikatami, błąd nie przerywa reszty."""
    print("--- Synchronizacja danych kampanii (dwukierunkowa) ---")
    try:
        report = CampaignSync().run(dry_run=dry_run, force=force)
    except SyncError as e:
        print(f"[OSTRZEŻENIE] Synchronizacja kampanii: {e}")
        return None
    prefix = "[INFO] Plan" if dry_run else "[SUKCES] Kampanie"
    print(f"{prefix}: {report.summary()}")
    for label, items in (("↑", report.uploaded), ("↓", report.downloaded), ("✗ Drive", report.deleted_remote),
                         ("✗ lokalnie", report.deleted_local)):
        for rel in items:
            print(f"  {label} {rel}")
    if report.pending:
        print(f"[OSTRZEŻENIE] Konflikty do rozstrzygnięcia ({len(report.pending)}): {', '.join(report.pending)} - "
              "w oknie programu albo: rpg-chronicler sync-campaigns --rozstrzygnij PLIK --zostaw moja|drive|obie")
    return report
