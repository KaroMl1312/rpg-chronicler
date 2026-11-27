// RPG Chronicles - okno „Prompty AI”: podgląd i edycja promptów (zmiany lokalnie, domyślne zostają w programie).

const prompts = { dialog: null, current: null, text: null, base: "" };

function promptEditorDirty() {
  return !!(prompts.text && prompts.text.value !== prompts.base);
}

async function promptsDialog(name) {
  let list;
  try { list = await api("/api/prompts"); } catch (e) { return toast(e.message); }
  const nav = el("div", { class: "prompt-list" });
  const editor = el("div", { class: "prompt-editor" });
  const dialog = openDialog("Prompty AI", el("div", { class: "prompts-layout" }, nav, editor), {
    cls: "prompts",
    onclose: () => { prompts.dialog = prompts.text = prompts.current = null; prompts.base = ""; },
  });
  prompts.dialog = dialog;
  // zamknięcie (krzyżyk, Escape) nie może zgubić wpisanego tekstu
  const closeButton = dialog.querySelector(".dlg-head .btn");
  const guarded = closeButton.cloneNode(true);
  closeButton.replaceWith(guarded);
  const tryClose = async () => {
    if (promptEditorDirty() && !(await confirmDiscard("Prompt ma niezapisane zmiany."))) return;
    dialog.close();
  };
  guarded.addEventListener("click", tryClose);
  // Escape przechwytywany już przy klawiszu: Chrome pozwala zablokować „cancel” tylko po świeżej akcji użytkownika
  dialog.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); tryClose(); } });
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); tryClose(); });

  const render = (items) => {
    nav.replaceChildren();
    let group = null;
    for (const item of items) {
      if (item.group !== group) { group = item.group; nav.append(el("div", { class: "prompt-group" }, group)); }
      nav.append(el("button", {
        class: `prompt-item${item.name === prompts.current ? " active" : ""}`,
        onclick: () => openPrompt(item.name),
      }, el("span", {}, item.title),
         item.default_updated ? el("span", { class: "badge warn", title: "Domyślny prompt zmienił się w nowej wersji programu" }, "nowa wersja")
           : item.changed ? el("span", { class: "badge" }, "zmieniony") : null));
    }
    nav.append(el("div", { class: "hint prompt-folder" }, `Zmienione prompty: ${list.folder}`));
  };
  const reloadList = async () => { try { list = await api("/api/prompts"); render(list.items); } catch (e) { toast(e.message); } };

  async function openPrompt(key) {
    if (key === prompts.current) return;
    if (promptEditorDirty() && !(await confirmDiscard("Prompt ma niezapisane zmiany."))) return;
    let data;
    try { data = await api(`/api/prompt?name=${encodeURIComponent(key)}`); } catch (e) { return toast(e.message); }
    prompts.current = key;
    render(list.items);
    showPrompt(data);
  }

  function showPrompt(data) {
    const text = el("textarea", { class: "prompt-text mono", spellcheck: false });
    text.value = data.text;
    prompts.text = text;
    prompts.base = data.text;
    const warnings = el("div", { class: "prompt-warnings" });
    const showWarnings = (items) => warnings.replaceChildren(
      ...items.map((w) => el("div", { class: "notice warn" }, w)));
    showWarnings(data.warnings);

    const save = button("Zapisz", async () => {
      try {
        const r = await api("/api/prompt", { name: data.name, text: text.value });
        prompts.base = text.value = r.text;
        save.disabled = true;
        showWarnings(r.warnings);
        await reloadList();
        updateStatus(r);
        toast(r.changed ? `Zapisano: ${r.title}` : `${r.title}: taki sam jak domyślny - używany domyślny`);
      } catch (e) { toast(e.message); }
    }, "btn suggested", { disabled: true });
    const reset = button("Przywróć domyślny", async () => {
      const answer = await ask("Przywrócić domyślny prompt?", `Twoja wersja promptu „${data.title}” zostanie usunięta.`,
                               [["no", "Anuluj"], ["yes", "Przywróć domyślny", "destructive"]]);
      if (answer !== "yes") return;
      try {
        const r = await api("/api/prompt/reset", { name: data.name });
        await reloadList();
        showPrompt(r);
        toast(`Przywrócono domyślny: ${r.title}`);
      } catch (e) { toast(e.message); }
    });
    const showDefault = button("Pokaż domyślny", () => {
      const view = el("textarea", { class: "prompt-text mono", readonly: true, spellcheck: false });
      view.value = data.default;
      openDialog(`Domyślny prompt: ${data.title}`, view, { cls: "prompts-default" });
    });
    const status = el("div", { class: "hint" });
    const updateStatus = (d) => {
      reset.hidden = !d.changed;
      showDefault.hidden = !d.changed;
      status.textContent = d.default_updated
        ? "Domyślny prompt zmienił się w nowej wersji programu, a używana jest Twoja wersja. Porównaj ją z domyślnym."
        : d.changed ? "Używana jest Twoja wersja." : "Używany jest domyślny prompt programu.";
      status.classList.toggle("warn-text", !!d.default_updated);
    };
    updateStatus(data);
    text.addEventListener("input", () => { save.disabled = text.value === prompts.base; });
    text.addEventListener("keydown", (e) => {
      if (e.ctrlKey && e.key === "s") { e.preventDefault(); if (!save.disabled) save.click(); }
    });

    const insert = (field) => {
      const token = `{${field}}`;
      text.focus();
      text.setRangeText(token, text.selectionStart, text.selectionEnd, "end");
      text.dispatchEvent(new Event("input"));
    };
    const chips = el("div", { class: "prompt-fields" },
      ...data.fields.map((f) => el("button", { class: "chip", title: `AI dostaje tu ${f.description}. Kliknij, żeby wstawić.`,
                                              onclick: () => insert(f.name) }, `{${f.name}}`)));
    const legend = el("details", { class: "prompt-legend" }, el("summary", {}, "Co oznaczają pola"),
      el("ul", {}, ...data.fields.map((f) => el("li", {}, el("code", {}, `{${f.name}}`), ` – ${f.description}`))),
      el("p", { class: "hint" }, "Program wstawia w pola dane sesji i kampanii. Pozostały tekst trafia do AI dosłownie, "
         + "także klamry, np. przykłady JSON."),
      data.cache_mark ? el("p", { class: "hint" }, `Linia ${data.cache_mark} oddziela stały początek promptu (API Anthropic `
         + "czyta go taniej przy kolejnych zapytaniach) od reszty - zostaw ją w osobnej linii.") : null);

    editor.replaceChildren(
      el("div", { class: "prompt-head" }, el("h3", {}, data.title), status),
      el("div", { class: "desc" }, data.description),
      chips, legend, warnings, text,
      el("div", { class: "actions" }, showDefault, reset, el("span", { class: "grow" }), save));
  }

  render(list.items);
  const first = list.items.find((x) => x.name === name) || list.items[0];
  if (first) await openPrompt(first.name);
}
