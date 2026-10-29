import os
import tempfile
from contextlib import contextmanager
from unittest import mock

from rpg_chronicler import session as session_mod
from rpg_chronicler import summary
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import save_speaker_mapping

TRANSCRIPT = "[SPEAKER_00] [0.00s -> 2.00s]  Witajcie w Altdorfie.\n"


class FakeLLM:
    name = "Fake"

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return "KRONIKA"


@contextmanager
def workspace(*names):
    """Tymczasowe katalogi z transkrypcjami i atrapą LLM zamiast prawdziwego klienta."""
    with tempfile.TemporaryDirectory() as tmp:
        dirs = {key: os.path.join(tmp, key) for key in ("audio", "txt", "summary")}
        for path in dirs.values():
            os.makedirs(path)
        for name in names:
            with open(os.path.join(dirs["txt"], f"{name}.txt"), "w", encoding="utf-8") as f:
                f.write(TRANSCRIPT)
        llm = FakeLLM()
        with mock.patch.multiple(session_mod, AUDIO_DIR=dirs["audio"], TXT_DIR=dirs["txt"],
                                 SUMMARY_DIR=dirs["summary"]), \
                mock.patch.object(summary, "SUMMARY_DIR", dirs["summary"]), \
                mock.patch.object(summary, "get_client", lambda provider: llm):
            yield llm


def test_non_interactive_skips_sessions_without_speakers():
    with workspace("Warhammer_1") as llm:
        summary.summarize_sessions(list_sessions(), interactive=False)
        assert llm.prompts == []
        assert not list_sessions()[0].has_summary


def test_allow_unnamed_summarizes_without_speakers():
    with workspace("Warhammer_1") as llm:
        summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
        session = list_sessions()[0]
        assert session.has_summary
        assert "SPEAKER_00: Witajcie w Altdorfie." in llm.prompts[0]


def test_uses_saved_speaker_names_and_skips_existing_summaries():
    with workspace("Warhammer_1") as llm:
        save_speaker_mapping(list_sessions()[0].txt_path, {"SPEAKER_00": "MG"})
        summary.summarize_sessions(list_sessions(), interactive=False)
        assert "MG: Witajcie w Altdorfie." in llm.prompts[0]
        assert "**Warhammer**" in llm.prompts[0]

        summary.summarize_sessions(list_sessions(), interactive=False)
        assert len(llm.prompts) == 1


def test_force_regenerates_summary():
    with workspace("Warhammer_1") as llm:
        summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
        summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True, force=True)
        assert len(llm.prompts) == 2


def test_select_sessions_by_name_or_filename():
    with workspace("Warhammer_1", "Fallout_2"):
        assert [s.name for s in list_sessions(["Fallout_2.txt"])] == ["Fallout_2"]
        assert [s.name for s in list_sessions()] == ["Fallout_2", "Warhammer_1"]
