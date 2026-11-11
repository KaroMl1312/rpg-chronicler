"""python -m rpg_chronicler.gui [--instaluj | --odinstaluj]"""
import os
import sys

from .desktop import install, uninstall


def _launcher() -> str:
    # Skrypt ./rpg-chronicler-gui ustawia RPG_CHRONICLER_LAUNCHER na swoją pełną ścieżkę
    return os.environ.get("RPG_CHRONICLER_LAUNCHER") or os.path.abspath(sys.argv[0])


if __name__ == "__main__":
    if "--instaluj" in sys.argv[1:]:
        for path in install(_launcher()):
            print(f"[SUKCES] Zapisano {path}")
        print("RPG Chronicler jest w menu aplikacji GNOME (może być potrzebne ponowne zalogowanie).")
        sys.exit(0)
    if "--odinstaluj" in sys.argv[1:]:
        removed = uninstall()
        print("\n".join(f"[SUKCES] Usunięto {p}" for p in removed) or "Nic do usunięcia.")
        sys.exit(0)

    from .app import main
    sys.exit(main())
