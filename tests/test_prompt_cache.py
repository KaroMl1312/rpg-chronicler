"""Cache promptów w API Anthropic: stały początek zapytań (prefix) musi być identyczny, żeby był czytany z cache."""
from types import SimpleNamespace

from rpg_chronicler import after_chronicle, chronicle_events, llm, memory, summary
from rpg_chronicler.llm.anthropic_api import AnthropicClient
from rpg_chronicler.prompts import chronicle_blocks, render, render_split
from rpg_chronicler.session import list_sessions
from rpg_chronicler.transcript import Segment, Transcript

LEGACY = "[0.00s -> 2.00s]  Witajcie.\n"


class CachingLLM:
    """Atrapa klienta z cache: zapisuje (prefix, prompt) każdego zapytania."""
    name = "Cache"
    caches_prefix = True

    def __init__(self, responses):
        self.calls = []
        self._responses = iter(responses)

    def generate(self, prompt, prefix=""):
        self.calls.append((prefix, prompt))
        return next(self._responses)


def test_render_split_joins_to_render():
    values = dict(system_name="W", part="2", parts="3", time_range="0:45:00–1:30:00", speaker_mapping_info="",
                  campaign_context="\n\nKONTEKST", previous_events="", transcript="TEKST")
    prefix, rest = render_split("events", **values)
    assert prefix + rest == render("events", **values)
    assert "KONTEKST" in prefix and "część 2 z 3" not in prefix and "TEKST" in rest
    assert render_split("brief", system_name="W") == ("", render("brief", system_name="W"))


def test_chronicle_blocks_keep_newest_within_limit():
    blocks = chronicle_blocks([("A_1", "a" * 50), ("A_2", "b" * 50)], limit=80)
    assert 'sesja="A_2"' in blocks and 'sesja="A_1"' not in blocks and blocks.endswith("</kronika>\n\n")


def test_generate_helper_sends_prefix_only_to_caching_clients():
    plain = SimpleNamespace(generate=lambda prompt: prompt)
    assert llm.generate(plain, "PYTANIE", "KRONIKA ") == "KRONIKA PYTANIE"
    caching = CachingLLM(["ok"])
    assert llm.generate(caching, "PYTANIE", "KRONIKA ") == "ok"
    assert caching.calls == [("KRONIKA ", "PYTANIE")]


def test_anthropic_client_marks_prefix_for_cache(capsys):
    sent = {}

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            usage = SimpleNamespace(cache_read_input_tokens=900, cache_creation_input_tokens=0, input_tokens=40)
            return SimpleNamespace(stop_reason="end_turn", usage=usage,
                                   content=[SimpleNamespace(type="text", text="ODPOWIEDŹ")])

    def stream(**kwargs):
        sent.update(kwargs)
        return Stream()

    client = AnthropicClient.__new__(AnthropicClient)
    client._anthropic = SimpleNamespace(RateLimitError=KeyError, APIConnectionError=KeyError, APIStatusError=KeyError)
    client.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    client.model, client.effort = "claude-opus-5-5", "medium"

    assert client.generate("PYTANIE", prefix="KRONIKA") == "ODPOWIEDŹ"
    assert sent["messages"][0]["content"] == [
        {"type": "text", "text": "KRONIKA", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "PYTANIE"},
    ]
    assert "odczyt 900 tokenów" in capsys.readouterr().out
    client.generate("BEZ PREFIKSU")
    assert sent["messages"][0]["content"] == "BEZ PREFIKSU"


def test_requests_after_chronicle_share_identical_prefix(workspace, monkeypatch):
    monkeypatch.setattr(after_chronicle, "CHRONICLE_BRIEF", True)
    monkeypatch.setattr(after_chronicle, "GLOSSARY_PROPOSALS", True)
    monkeypatch.setattr(after_chronicle, "CAMPAIGN_MEMORY", True)
    memory.save_state("Fallout", "## Drużyna\n- Fen", "Fallout_260930")
    workspace.add_transcript("Fallout_261014", LEGACY)
    fake = CachingLLM(["KRONIKA SESJI", "SKRÓT", '{"npc": []}', "## Drużyna\n- Fen ranny"])
    monkeypatch.setattr(llm, "get_client", lambda provider: fake)

    summary.summarize_sessions(list_sessions(), interactive=False)
    (_, chronicle), brief, glossary_call, memory_call = fake.calls
    assert brief[0] == glossary_call[0] == memory_call[0] == chronicle_blocks([("Fallout_261014", "KRONIKA SESJI")])
    assert "streszczenie" in brief[1] and "JSON" in glossary_call[1] and "## Drużyna\n- Fen" in memory_call[1]


def test_event_parts_share_identical_prefix(workspace, monkeypatch):
    monkeypatch.setattr(chronicle_events, "CHRONICLE_TWO_STEP", True)
    segments = [Segment(i * 60.0, i * 60.0 + 50, f"wypowiedź {i}", f"SPEAKER_0{i // 4 % 2}") for i in range(140)]
    workspace.add_transcript("Fallout_261014", Transcript(segments=segments).to_txt())
    fake = CachingLLM(["W1", "W2", "W3", "KRONIKA"])
    monkeypatch.setattr(llm, "get_client", lambda provider: fake)

    summary.summarize_sessions(list_sessions(), interactive=False, allow_unnamed=True)
    parts = fake.calls[:3]
    assert len({prefix for prefix, _ in parts}) == 1 and parts[0][0]
    assert ["część 1 z 3" in parts[0][1], "część 3 z 3" in parts[2][1]] == [True, True]
    assert fake.calls[3][0] == ""   # kronika z wydarzeń - jedno zapytanie, bez cache
