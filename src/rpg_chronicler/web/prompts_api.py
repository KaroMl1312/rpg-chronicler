"""Okno „Prompty AI”: lista promptów, podgląd, zapis zmian i przywracanie domyślnych."""
from ..prompts import catalog, custom


def _item(name: str) -> dict:
    group, title, _ = catalog.info(name)
    return {"name": name, "group": group, "title": title, **custom.status(name)}


def prompt_list() -> dict:
    items = [_item(n) for n in custom.names()]
    order = {g: i for i, g in enumerate(catalog.GROUPS)}
    items.sort(key=lambda x: (order.get(x["group"], len(order)), x["title"]))
    return {"items": items, "folder": str(custom.prompts_dir())}


def prompt(name: str) -> dict:
    custom._check(name)
    base = custom.default(name)
    text = custom.to_display(custom.template(name))
    _, title, description = catalog.info(name)
    return {**_item(name), "description": description, "text": text, "default": custom.to_display(base),
            "fields": [{"name": f, "description": catalog.field_description(f)} for f in custom.fields(base)],
            "cache_mark": custom.CACHE_MARK if custom.CACHE_MARK in base else "",
            "warnings": custom.warnings(name, text)}


def save(name: str, text: str) -> dict:
    warnings = custom.save(name, str(text))
    return {**prompt(name), "warnings": warnings}


def reset(name: str) -> dict:
    custom.reset(name)
    return prompt(name)
