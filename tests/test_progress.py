from rpg_chronicler import progress


def test_report_is_silent_without_env(monkeypatch, capsys):
    monkeypatch.delenv(progress.ENV_VAR, raising=False)
    progress.report("transkrypcja", "Zakon_1", 10, 100)
    assert capsys.readouterr().out == ""


def test_report_and_parse_roundtrip(monkeypatch, capsys):
    monkeypatch.setenv(progress.ENV_VAR, "json")
    progress.report("transkrypcja", "Zakon_1", 25, 100)
    line = capsys.readouterr().out.strip()
    data = progress.parse(line)
    assert data == {"etap": "transkrypcja", "sesja": "Zakon_1", "zrobione": 25.0, "razem": 100.0}
    assert progress.fraction(data) == 0.25


def test_parse_ignores_other_lines():
    assert progress.parse("[SUKCES] Zapisano") is None
    assert progress.parse(progress.PREFIX + "{zepsute") is None
    assert progress.fraction({"etap": "kronika", "zrobione": None, "razem": None}) is None


def test_report_accepts_numpy_like_numbers(monkeypatch, capsys):
    class Int64:  # jak numpy.int64: nie jest int-em, json go nie zna, ale da się go zamienić na float
        def __init__(self, value):
            self.value = value

        def __float__(self):
            return float(self.value)

    monkeypatch.setenv(progress.ENV_VAR, "json")
    progress.report("segmentacja", None, Int64(3), Int64(51))
    assert progress.parse(capsys.readouterr().out.strip())["razem"] == 51.0
