from importlib.resources import files


def render(name: str, **values: str) -> str:
    """Wczytuje szablon promptu `prompts/<name>.md` i podstawia wartości {pól}."""
    template = files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")
    return template.format(**values)
