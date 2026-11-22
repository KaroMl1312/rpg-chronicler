import re
from decimal import Decimal

from rpg_chronicler import version
from rpg_chronicler.cli.parser import build_parser


def test_version_matches_newest_changelog_entry():
    releases = version.releases()
    assert releases, "nowosci.md bez nagłówków ## WERSJA – DATA"
    assert releases[0][0] == version.VERSION
    assert re.fullmatch(r"\d+\.\d{3}", version.VERSION)


def test_versions_go_up_by_one_thousandth_from_1_000():
    numbers = [Decimal(v) for v, _date in reversed(version.releases())]
    assert numbers[0] == Decimal("1.000")
    assert all(b - a == Decimal("0.001") for a, b in zip(numbers, numbers[1:])), numbers
    dates = [d for _v, d in reversed(version.releases())]
    assert dates == sorted(dates)


def test_every_release_has_entries():
    text = version.changelog()
    parts = version.HEADER_RE.split(text)[1:]
    for ver, _date, body in zip(parts[::3], parts[1::3], parts[2::3]):
        assert "\n- " in body, f"wersja {ver} bez punktów"


def test_cli_version(capsys):
    try:
        build_parser().parse_args(["--version"])
    except SystemExit:
        pass
    assert capsys.readouterr().out.strip() == f"rpg-chronicler {version.VERSION}"
