"""Opisy promptów i ich pól dla edytora promptów (okno „Prompty AI”). Tylko stdlib."""

CHRONICLE = "Przed promptem AI dostaje kronikę sesji."
CHRONICLES = "Przed promptem AI dostaje kroniki kampanii (najnowsze, jeśli wszystkie się nie mieszczą)."

# nazwa -> (grupa, tytuł, opis: kiedy program go używa i co dostaje AI)
PROMPTS: dict[str, tuple[str, str, str]] = {
    "summary": ("Kronika", "Kronika sesji",
                "Pisze kronikę z transkrypcji, a przy długich sesjach z listy wydarzeń części."),
    "events": ("Kronika", "Lista wydarzeń części",
               "Długie sesje (ponad ok. 1 h): z każdej 45-minutowej części transkrypcji AI robi listę wydarzeń "
               "z cytatami, z której potem powstaje kronika."),
    "summary_notes": ("Kronika", "Kronika z notatek MG",
                      "Sesje bez nagrania: rozwija notatki Mistrza Gry w kronikę."),
    "revise": ("Kronika", "Poprawka kroniki",
               "„Popraw…” w zakładce Kronika: zmienia kronikę według Twojego polecenia. " + CHRONICLE),
    "brief": ("Po kronice", "Skrót kroniki",
              "Po każdej nowej kronice: jeden akapit o najważniejszych wydarzeniach. " + CHRONICLE),
    "quotes": ("Po kronice", "Cytaty z sesji",
               "Po każdej nowej kronice: wypowiedzi z gry z czasem nagrania. " + CHRONICLE),
    "teaser": ("Po kronice", "Zapowiedź na Discord",
               "Krótki tekst nad kroniką wysyłaną na Discord."),
    "glossary_extraction": ("Kampania", "Propozycje słownika",
                            "Po nowej kronice i przy „Słownik z kronik”: nazwy postaci, miejsc i przedmiotów "
                            "do słownika kampanii. " + CHRONICLES),
    "campaign_state": ("Kampania", "Pamięć kampanii",
                       "Po nowej kronice: aktualizacja stanu kampanii (drużyna, zasoby, wątki, BN-i). "
                       + CHRONICLES),
    "encyclopedia": ("Kampania", "Encyklopedia kampanii",
                     "Hasła encyklopedii z opisami i sesjami, w których występują. " + CHRONICLES),
    "diary": ("Kampania", "Dziennik postaci",
              "Wpis z perspektywy postaci o jednej sesji. " + CHRONICLE),
    "recap": ("Przed sesją", "Poprzednio w kampanii…",
              "Tekst do przeczytania na głos na początku sesji. Przed promptem AI dostaje ostatnią kronikę."),
    "session_ideas": ("Przed sesją", "Pomysły na następną sesję",
                      "Pomysły na wydarzenia dla MG. Przed promptem AI dostaje ostatnią kronikę."),
    "gm_notes": ("Przed sesją", "Notatki MG",
                 "Otwarte wątki, obietnice, tropy i BN-i do przypomnienia. " + CHRONICLES),
    "ask": ("Przed sesją", "Zapytaj kronikarza",
            "Odpowiedź na pytanie o kampanię ze wskazaniem sesji. " + CHRONICLES),
    "speaker_identification": ("Mówcy", "Sugestia mówców",
                               "Zgaduje, kto jest kim (SPEAKER_00 → MG, postać…) z początku transkrypcji."),
    "image_style": ("Obrazki", "Styl obrazków kampanii",
                    "Propozycja stylu, gdy kampania nie ma go jeszcze ustawionego."),
    "image_prompt": ("Obrazki", "Opis obrazka hasła",
                     "Pisze po angielsku opis obrazka dla modelu rysującego (FLUX)."),
}
GROUPS = ["Kronika", "Po kronice", "Kampania", "Przed sesją", "Mówcy", "Obrazki"]

FIELDS: dict[str, str] = {
    "system_name": "nazwę systemu RPG kampanii",
    "campaign_info": "informacje o kampanii (opis świata, postacie graczy, słownik nazw)",
    "campaign_context": "informacje o kampanii, stan kampanii i kronikę poprzedniej sesji",
    "speaker_mapping_info": "listę mówców (kto jest MG, kto jaką postacią)",
    "source": "materiał z sesji (transkrypcję, listę wydarzeń albo notatki)",
    "source_description": "opis, skąd pochodzi materiał (lista wydarzeń czy transkrypcja)",
    "source_note": "opis materiału źródłowego dołączonego do poprawki",
    "transcript": "transkrypcję (albo jej fragment)",
    "part": "numer części transkrypcji",
    "parts": "liczbę części transkrypcji",
    "time_range": "zakres czasu części nagrania",
    "previous_events": "wydarzenia poprzedniej części",
    "instruction": "Twoje polecenie poprawki",
    "count_rule": "zasadę, ile cytatów wybrać (zależnie od liczby postaci)",
    "chronicle": "kronikę sesji",
    "current_glossary": "obecny słownik kampanii",
    "description_field": "pole opisu hasła w odpowiedzi JSON (gdy brakuje opisu kampanii)",
    "description_rule": "zasadę pisania opisu kampanii (gdy go brakuje)",
    "previous_state": "poprzedni stan kampanii",
    "state": "stan kampanii (pamięć kampanii)",
    "session_name": "nazwę sesji",
    "count": "liczbę pomysłów",
    "previous": "poprzednie pomysły (żeby się nie powtarzały)",
    "question": "Twoje pytanie",
    "character": "imię postaci",
    "also_known": "inne formy imienia postaci w kronice",
    "own_quotes": "cytaty postaci z tej sesji",
    "previous_entry": "poprzedni wpis dziennika",
    "entry": "nazwę hasła",
    "category": "kategorię hasła (postać, BN, miejsce…)",
    "description": "opis hasła",
    "style": "styl obrazków kampanii",
    "user_hints": "Twoje wskazówki do obrazka",
}


def field_description(field: str) -> str:
    return FIELDS.get(field, field)


def info(name: str) -> tuple[str, str, str]:
    return PROMPTS.get(name, ("Inne", name, ""))
