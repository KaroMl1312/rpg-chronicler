// RPG Chronicles - nowe okno, etap 3: zakładka Kampanie (lista, podzakładki Ogólne / Słownik / Przed sesją /
// Dokumenty, strona hasła z opisem i obrazkiem). Korzysta z funkcji z app.js i sesja.js.
"use strict";

const CAMPAIGN_TABS = [["ogolne", "Ogólne"], ["slownik", "Słownik"], ["przed-sesja", "Przed sesją"],
                       ["dokumenty", "Dokumenty"]];
const PREVIEW_CHARS = 90;
const NO_DESCRIPTION = "Brak opisu - kliknij, żeby dodać opis albo zdjęcie.";

const camp = {
  list: null,            // /api/campaigns
  key: null,             // otwarta kampania
  data: null,            // /api/campaign
  tab: "ogolne",
  entry: null,           // nazwa otwartego hasła (strona hasła zamiast podzakładki)
  entryData: null,
  expanded: new Set(),   // rozwinięte listy nazw
  drafts: new Map(),     // wpisane, ale niezapisane teksty (id pola -> {value, base, long})
  request: 0,            // numer ostatniego wczytywania - spóźniona odpowiedź nie nadpisuje nowszego widoku
};

// --- lista kampanii -------------------------------------------------------------------------------------

async function loadCampaignList() {
  camp.list = await api("/api/campaigns");
  $("#campaign-list").replaceChildren(...camp.list.campaigns.map((c) => {
    const sub = [c.system, c.proposals ? `${c.proposals} propozycji AI` : "", c.new_state ? "nowy stan do przejrzenia" : ""];
    return el("li", { class: c.key === camp.key ? "active" : "", onclick: () => openCampaign(c.key) },
      el("div", { class: "names" }, el("div", { class: "name" }, c.key), el("div", { class: "sub" }, sub.filter(Boolean).join(" · "))),
      c.proposals || c.new_state ? el("span", { class: "dot", title: "Propozycje AI do przejrzenia" }) : null);
  }));
}

function addCampaignMenu(e) {
  e.stopPropagation();
  popover(e.currentTarget, [
    ...(camp.list.missing.length ? [{ section: "Prefiksy nagrań bez kampanii" }] : []),
    ...camp.list.missing.map((key) => ({ label: key, onclick: () => createCampaign(key) })),
    ...(camp.list.missing.length ? ["-"] : []),
    { label: "Inna nazwa…", onclick: newCampaignDialog },
  ]);
}

function newCampaignDialog() {
  const input = el("input", { type: "text", placeholder: "np. Warhammer" });
  const error = el("div", { class: "error-text" });
  const run = async () => { if (await createCampaign(input.value, error)) dialog.close(); };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  const dialog = openDialog("Dodaj kampanię", [
    el("div", { class: "field" }, el("div", { class: "hint" }, "Kampania to prefiks nazwy nagrania przed pierwszym „_”, "
      + "np. Warhammer_261015 → Warhammer."), input, error)],
    { footer: [button("Anuluj", () => dialog.close()), button("Dodaj", run, "btn suggested")] });
  input.focus();
}

async function createCampaign(key, error) {
  try {
    const r = await api("/api/campaigns", { key });
    await openCampaign(r.key);
    return true;
  } catch (e) {
    if (error) error.textContent = e.message; else toast(e.message);
    return false;
  }
}

// --- otwieranie i odświeżanie -----------------------------------------------------------------------------

async function showCampaign(key, tab) {
  if (!(await leaveEntry())) return;
  collectDrafts();
  if (tab) camp.tab = tab;
  if (key && key !== camp.key) { camp.key = key; camp.data = null; camp.expanded.clear(); }
  await showMain("kampanie");
}

async function openCampaign(key) {
  if (!(await leaveEntry())) return;
  collectDrafts();
  if (key !== camp.key) { camp.key = key; camp.data = null; camp.expanded.clear(); }
  await renderCampaigns();
}

// Cały widok kampanii od nowa (po zmianie, po zadaniu) - z zachowaniem przewinięcia i niedokończonych wpisów
async function renderCampaigns() {
  const request = ++camp.request;
  let data = null, entryData = null;
  try {
    await loadCampaignList();
    if (camp.key) data = await api(`/api/campaign?key=${encodeURIComponent(camp.key)}`);
    if (camp.key && camp.entry) {
      entryData = await api(`/api/entry?key=${encodeURIComponent(camp.key)}&name=${encodeURIComponent(camp.entry)}`)
        .catch(() => null);   // hasło usunięte w międzyczasie - wracamy do słownika
      if (!entryData) camp.entry = null;
    }
  } catch (e) { return toast(e.message); }
  if (request !== camp.request || state.main !== "kampanie") return;
  camp.data = data;
  camp.entryData = entryData;
  drawCampaign();
}

function drawCampaign() {
  $("#toolbar").hidden = true;
  $("#session-tabs").hidden = true;
  $("#header-right").replaceChildren();
  const view = $("#view");
  const tabs = $("#campaign-tabs");
  hideTip();
  if (!camp.data) {
    tabs.hidden = true;
    $("#session-name").textContent = "";
    view.replaceChildren(el("div", { class: "empty" }, el("h2", {}, "Wybierz kampanię"),
      el("div", { class: "narrow" }, "Po lewej są kampanie (prefiksy nazw nagrań). Kampania to opis świata, postacie graczy, "
        + "słownik nazw z opisami i zdjęciami, pamięć kampanii, materiały przed sesją, encyklopedia i dzienniki postaci.")));
    return;
  }
  const c = camp.data;
  $("#session-name").textContent = c.key;
  tabs.hidden = false;
  tabs.replaceChildren(...CAMPAIGN_TABS.map(([key, label]) => el("button", {
    class: key === camp.tab ? "active" : "",
    onclick: async () => {
      if (!(await leaveEntry())) return;
      collectDrafts();
      camp.tab = key;
      view.scrollTop = 0;
      renderCampaigns();
    } }, label,
    key === "slownik" && c.proposals.count ? el("span", { class: "badge", title: "Propozycje AI" }, c.proposals.count) : null,
    key === "ogolne" && c.proposal ? el("span", { class: "dot", title: "Nowy stan kampanii do przejrzenia" }) : null)));

  collectDrafts();
  const place = `${c.key}/${camp.tab}/${camp.entry || ""}`;
  const scroll = view.dataset.place === place ? view.scrollTop : 0;
  const page = el("div", { class: "page" });
  if (camp.entry) page.append(...entryPage());
  else if (camp.tab === "ogolne") page.append(generalGroup(), memoryGroup(), webhookGroup());
  else if (camp.tab === "slownik") {
    page.append(proposalsGroup(), descriptionsGroup(), charactersGroup(), ...c.categories.map(namesGroup));
  } else if (camp.tab === "przed-sesja") page.append(prepGroup(), askGroup());
  else page.append(encyclopediaGroup(), diariesGroup());
  view.replaceChildren(page);
  view.dataset.place = place;
  restoreDrafts();
  view.scrollTop = scroll;
  updateTaskButtons();
}

// Pola z data-draft: tekst wpisany, ale jeszcze niezapisany, przeżywa odświeżenie widoku (np. koniec zadania)
// i przejście na inną zakładkę. data-base to tekst, od którego zaczęto - gdy zapisana wersja się zmieniła,
// wpis zostaje, a okno ostrzega.
function collectDrafts() {
  for (const node of document.querySelectorAll("#view [data-draft]")) {
    const id = node.dataset.draft;
    if (node.value === node.dataset.base) camp.drafts.delete(id);
    else camp.drafts.set(id, { value: node.value, base: node.dataset.base, long: node.tagName === "TEXTAREA" });
  }
}

function restoreDrafts() {
  for (const node of document.querySelectorAll("#view [data-draft]")) {
    const draft = camp.drafts.get(node.dataset.draft);
    if (!draft || draft.value === node.value) continue;
    if (draft.base !== node.dataset.base) toast("Zapisana treść zmieniła się w międzyczasie - sprawdź swój niezapisany tekst");
    node.value = draft.value;
    node.dispatchEvent(new Event("input"));
  }
}

function draftField(node, id, base) {
  node.value = base;
  node.dataset.draft = `${camp.key}/${id}`;
  node.dataset.base = base;
  return node;
}

// Po udanym zapisie pole nie jest już szkicem
function draftSaved(node) { node.dataset.base = node.value; }

async function changeCampaign(what, body, message) {
  try {
    await api("/api/campaign", { key: camp.key, what, ...body });
    if (message) toast(message);
    await renderCampaigns();
    return true;
  } catch (e) { toast(e.message); return false; }
}

function campaignTask(label, title, args, cls = "btn flat", tooltip = "") {
  return taskButton(label, title, [...args, ...providerArgs()], cls, tooltip);
}

function groupBox(title, description, rows, side) {
  return el("div", { class: "group" },
    el("div", { class: "section-head" }, el("h3", {}, title), side),
    description ? el("div", { class: "desc" }, description) : null, rows);
}

function openFile(path) { api("/api/open", { path }).catch((e) => toast(e.message)); }

// Jednowierszowe pole z „Zapisz” (aktywnym dopiero po zmianie)
function textRow(label, hint, id, value, save) {
  const input = draftField(el("input", { type: "text" }), id, value);
  const run = async () => { const base = input.dataset.base; draftSaved(input); if (!(await save(input.value))) input.dataset.base = base; };
  const saveButton = button("Zapisz", run, "btn", { disabled: true });
  input.addEventListener("input", () => { saveButton.disabled = input.value === input.dataset.base; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !saveButton.disabled) run(); });
  return el("div", { class: "row" }, el("div", { class: "label" }, label, hint ? el("div", { class: "hint" }, hint) : null), input, saveButton);
}

// Pole „Dodaj…”: po dodaniu czyści się
function addRow(placeholder, id, add) {
  const input = draftField(el("input", { type: "text", class: "grow", placeholder }), id, "");
  const run = async () => {
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    if (!(await add(value))) input.value = value;
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  return el("div", { class: "row" }, input, button("Dodaj", run));
}

// --- Ogólne ------------------------------------------------------------------------------------------------

function generalGroup() {
  const c = camp.data;
  const context = draftField(el("textarea"), "context", c.context);
  const save = button("Zapisz opis", async () => {
    const base = context.dataset.base;
    draftSaved(context);
    if (!(await changeCampaign("context", { value: context.value }, "Zapisano opis kampanii"))) context.dataset.base = base;
  }, "btn suggested", { disabled: true });
  context.addEventListener("input", () => { save.disabled = context.value.trim() === context.dataset.base.trim(); });
  const rows = el("div", { class: "rows" },
    textRow("System RPG", "styl i słownictwo kroniki", "system", c.system, (value) => changeCampaign("system", { value }, "Zapisano system")),
    textRow("Styl obrazków AI", "po angielsku, np. „grimdark fantasy, ink and watercolor”; pusty - AI zaproponuje przy "
            + "pierwszym obrazku. Bez nazwisk artystów i nazw wydawców.", "image_style", c.image_style,
            (value) => changeCampaign("image_style", { value }, "Zapisano styl obrazków")));
  return groupBox("Ogólne", `Opis świata, postacie graczy i słownik nazw trafiają do transkrypcji (poprawna pisownia) i do kronik. Plik: ${c.file}`,
    [rows, el("div", { class: "field spaced" }, el("label", {}, "Opis świata i kampanii dla AI"),
       el("div", { class: "hint" }, "gdzie toczy się akcja, główny wątek, ton"), context, el("div", { class: "actions" }, save))]);
}

function memoryGroup() {
  const c = camp.data;
  const shown = c.proposal || c.state;
  let description;
  if (c.proposal) {
    description = `AI zaktualizowało stan po sesji ${c.proposal.session || "?"}. Popraw, co trzeba, i przyjmij - dopiero wtedy `
      + "trafi do kolejnych kronik.";
  } else if (c.state) {
    description = `Stan ${c.state.session ? `po sesji ${c.state.session}` : "wpisany ręcznie"}: drużyna, zasoby, otwarte wątki `
      + "i BN-i. Dostaje go AI piszące kronikę następnej sesji. Po każdej nowej kronice AI proponuje aktualizację.";
  } else {
    description = "Notatka o stanie kampanii (drużyna, zasoby, otwarte wątki, BN-i) dla AI piszącego kroniki. Zbuduj ją "
      + "z kronik albo wpisz ręcznie; potem aktualizuje się po każdej nowej kronice (do zatwierdzenia).";
  }
  const text = draftField(el("textarea", { class: "mono" }), c.proposal ? `proposal/${c.proposal.session}` : "state", shown ? shown.text : "");
  const act = async (action, message) => {
    const base = text.dataset.base;
    draftSaved(text);
    try {
      await api("/api/campaign/memory", { key: c.key, action, text: text.value, session: shown ? shown.session : null });
      toast(message);
      await renderCampaigns();
    } catch (e) { text.dataset.base = base; toast(e.message); }
  };
  const actions = el("div", { class: "actions" });
  if (c.proposal) {
    actions.append(button("Odrzuć", async () => {
      const answer = await ask("Odrzucić nowy stan kampanii?", "Propozycja AI zniknie; zostanie dotychczasowy stan.",
                               [["cancel", "Anuluj"], ["reject", "Odrzuć", "destructive"]]);
      if (answer === "reject") act("reject", "Odrzucono propozycję stanu kampanii");
    }, "btn flat"), button("Przyjmij", () => act("accept", "Przyjęto stan kampanii"), "btn suggested"));
  } else {
    const save = button("Zapisz stan", () => act("save", "Zapisano stan kampanii"), "btn suggested", { disabled: true });
    text.addEventListener("input", () => { save.disabled = text.value.trim() === text.dataset.base.trim(); });
    actions.append(save);
  }
  return groupBox("Pamięć kampanii" + (c.proposal ? " - nowa propozycja AI" : ""), description,
    el("div", {}, text, actions),
    campaignTask("Zbuduj z kronik", `Stan kampanii ${c.key}`, ["memory", c.key, "--rebuild"], shown ? "btn flat" : "btn suggested",
                 "AI przeczyta wszystkie kroniki tej kampanii i opisze jej obecny stan"));
}

function webhookGroup() {
  const c = camp.data;
  const input = el("input", { type: "password", autocomplete: "off",
    placeholder: c.webhook ? "ustawiony - wklej nowy, żeby zmienić" : "https://discord.com/api/webhooks/…" });
  const save = button("Zapisz", async () => {
    try {
      await api("/api/discord/webhook", { campaign: c.key, url: input.value });
      toast("Zapisano webhook");
      renderCampaigns();
    } catch (e) { toast(e.message); }
  });
  const side = c.webhook ? [
    taskButton("Wyślij test", `Test Discorda ${c.key}`, ["discord-test", c.key], "btn flat", "Wyślij na kanał krótką wiadomość testową"),
    button("Usuń webhook", async () => {
      const answer = await ask("Usunąć webhook?", `Kroniki kampanii ${c.key} nie będą wysyłane na Discord, dopóki nie wkleisz adresu od nowa.`,
                               [["cancel", "Anuluj"], ["remove", "Usuń", "destructive"]]);
      if (answer !== "remove") return;
      try { await api("/api/campaign/remove-webhook", { key: c.key }); renderCampaigns(); } catch (e) { toast(e.message); }
    }, "btn flat")] : null;
  return groupBox("Discord", "Kanał, na który trafiają kroniki tej kampanii. Na Discordzie: ustawienia kanału → Integracje → Webhooki → "
    + "Nowy webhook → Kopiuj adres URL. Adres zostaje tylko na tym komputerze (nie trafia na Google Drive).",
    el("div", { class: "rows" }, el("div", { class: "row" }, el("div", { class: "label" }, "Adres webhooka"), input, save)), side);
}

// --- Słownik --------------------------------------------------------------------------------------------------

function proposalsGroup() {
  const c = camp.data, p = c.proposals;
  const askAI = campaignTask("Uzupełnij z kronik", `Słownik kampanii ${c.key}`, ["glossary", c.key], p.count ? "btn flat" : "btn suggested",
                             "AI przejrzy wszystkie kroniki tej kampanii i zaproponuje nowe nazwy");
  if (!p.count) {
    return groupBox("Propozycje AI", "AI przejrzy kroniki tej kampanii i zaproponuje postacie, miejsca, przedmioty i inne nazwy. "
      + "Po każdej nowej kronice propozycje pojawiają się tu same.", null, askAI);
  }
  const boxes = [];
  const check = (category, value) => {
    const box = el("input", { type: "checkbox", checked: true });
    boxes.push({ category, value, box });
    return box;
  };
  const rows = el("div", { class: "rows" }, p.groups.map((g) => el("div", { class: "row block" },
    el("b", {}, `${g.label} (${g.names.length})`),
    el("div", { class: "checks" }, g.names.map((n) => el("label", {}, check(g.category, n), n))))));
  if (p.description) {
    rows.append(el("div", { class: "row block" }, el("label", { class: "checks" }, check("opis", p.description),
      el("b", {}, "Opis świata (kampania nie ma jeszcze opisu)")), el("div", { class: "hint" }, p.description)));
  }
  const resolve = async (accept) => {
    const shown = {}, accepted = {};
    for (const { category, value, box } of boxes) {
      for (const [target, include] of [[shown, true], [accepted, accept && box.checked]]) {
        if (!include) continue;
        if (category === "opis") target.opis = value; else (target[category] ||= []).push(value);
      }
    }
    try {
      const r = await api("/api/campaign/proposals", { key: c.key, shown, accepted });
      toast(r.added ? `Dodano do słownika: ${r.added}` : "Odrzucono propozycje");
      await renderCampaigns();
    } catch (e) { toast(e.message); }
  };
  return groupBox(`Propozycje AI (${p.count})`, "Odznacz to, czego nie chcesz w słowniku - niezaznaczone zostaną odrzucone.",
    [rows, el("div", { class: "actions" }, button("Odrzuć wszystkie", () => resolve(false), "btn flat"),
              button("Dodaj zaznaczone", () => resolve(true), "btn suggested"))], askAI);
}

function descriptionsGroup() {
  const c = camp.data;
  return groupBox("Opisy haseł", "Krótki opis postaci, BN-ów, miejsc i przedmiotów ze słownika poniżej - najedź na nazwę, żeby go zobaczyć, "
    + `kliknij, żeby edytować i dodać zdjęcie. Opisane: ${c.described} z ${c.names_count}.`, null,
    c.described < c.names_count ? campaignTask("Uzupełnij z kronik", `Opisy haseł kampanii ${c.key}`, ["describe", c.key], "btn flat",
      "AI opisze nazwy bez opisu na podstawie kronik (te same opisy co w encyklopedii); opisów wpisanych ręcznie nie zmienia") : null);
}

function imageUrl(name, version, proposal = false) {
  const params = new URLSearchParams({ key: camp.key, name, v: version, t: TOKEN });
  if (proposal) params.set("proposal", "1");
  return `/api/image?${params}`;
}

function shortText(text) {
  text = text.replace(/\s+/g, " ").trim();
  return text.length <= PREVIEW_CHARS ? text : text.slice(0, PREVIEW_CHARS - 1).trimEnd() + "…";
}

function removeButton(title, onclick) {
  return el("button", { class: "btn flat icon", title, html: ICONS.trash,
                        onclick: (e) => { e.stopPropagation(); hideTip(); onclick(); } });
}

// Wiersz hasła: miniatura, podgląd opisu, dymek; kliknięcie (albo Enter) otwiera stronę hasła
function entryRow(x, remove, extra) {
  const row = el("div", { class: "row link entry", tabindex: 0, role: "button",
    onclick: () => openEntry(x.name),
    onkeydown: (e) => { if (e.key === "Enter" && e.target === row) openEntry(x.name); } },
    x.image ? el("img", { class: "thumb", src: imageUrl(x.name, x.image), alt: "", loading: "lazy" }) : null,
    el("div", { class: "label" }, x.name, x.description ? el("div", { class: "hint one-line" }, shortText(x.description)) : null),
    extra, remove, el("span", { class: "icon dim", html: ICONS.next }));
  attachTip(row, x);
  return row;
}

function charactersGroup() {
  const c = camp.data;
  const rows = el("div", { class: "rows" }, c.characters.map((x) => {
    const player = draftField(el("input", { type: "text", class: "short", placeholder: "gracz (opcjonalnie)", title: "Gracz" }), `player/${x.name}`, x.player);
    const save = () => {
      if (player.value === player.dataset.base) return;
      const base = player.dataset.base;
      draftSaved(player);
      changeCampaign("set_player", { name: x.name, value: player.value }, `Zapisano gracza postaci ${x.name}`)
        .then((ok) => { if (!ok) player.dataset.base = base; });
    };
    player.addEventListener("click", (e) => e.stopPropagation());
    player.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") save(); });
    player.addEventListener("change", save);
    return entryRow(x, removeButton(`Usuń postać ${x.name}`, () => confirmRemove(x.name, () => changeCampaign("remove_character", { name: x.name }))), player);
  }), addRow("Dodaj postać (np. „Fen” albo „Fen = Ania”)", "add-character", (value) => changeCampaign("add_character", { value })));
  return groupBox("Postacie graczy", "Podpowiadane przy nazywaniu mówców; AI rozpoznaje po nich, kto jest kim. Gracz jest opcjonalny.", rows);
}

// Usunięcie nazwy kasuje też jej opis (przy zapisie kampanii), więc opisane hasła - z pytaniem
async function confirmRemove(name, remove) {
  const all = [...camp.data.characters, ...camp.data.categories.flatMap((g) => g.names)];
  const item = all.find((x) => x.name === name);
  if (item && item.description) {
    const answer = await ask(`Usunąć „${name}”?`, "Razem z nazwą zniknie jej opis.", [["cancel", "Anuluj"], ["remove", "Usuń", "destructive"]]);
    if (answer !== "remove") return;
  }
  remove();
}

function namesGroup(category) {
  const rows = el("div", { class: "rows" }, addRow("Dodaj (kilka nazw oddziel przecinkami)", `add/${category.key}`, (value) => {
    camp.expanded.add(category.key);
    return changeCampaign("add_names", { category: category.key, value });
  }));
  if (category.names.length) {
    const names = category.names.map((x) => x.name);
    const details = el("details", { class: "names-list", open: camp.expanded.has(category.key),
      ontoggle: (e) => { if (e.target.open) camp.expanded.add(category.key); else camp.expanded.delete(category.key); } },
      el("summary", {}, el("b", {}, `Nazwy (${names.length})`),
         el("span", { class: "hint" }, " " + names.slice(0, 6).join(", ") + (names.length > 6 ? "…" : ""))),
      category.names.map((x) => entryRow(x, removeButton(`Usuń ${x.name}`, () => confirmRemove(x.name,
        () => changeCampaign("remove_name", { category: category.key, name: x.name }))))));
    rows.append(details);
  }
  return groupBox(category.label, "", rows);
}

// --- dymek z opisem i zdjęciem ----------------------------------------------------------------------------------

let tipTimer = null;
function hideTip() { clearTimeout(tipTimer); for (const node of document.querySelectorAll(".tip")) node.remove(); }

function attachTip(row, x) {
  row.addEventListener("mouseenter", () => {
    hideTip();
    tipTimer = setTimeout(() => {
      if (!row.isConnected) return;
      const tip = el("div", { class: "tip" }, x.image ? el("img", { src: imageUrl(x.name, x.image), alt: "" }) : null,
                     el("b", {}, x.name), el("div", {}, x.description || NO_DESCRIPTION));
      document.body.append(tip);
      const rect = row.getBoundingClientRect();
      const below = rect.bottom + tip.offsetHeight + 8 < window.innerHeight;
      tip.style.top = `${below ? rect.bottom + 4 : Math.max(8, rect.top - tip.offsetHeight - 4)}px`;
      tip.style.left = `${Math.max(8, Math.min(rect.left + 40, window.innerWidth - tip.offsetWidth - 8))}px`;
    }, 450);
  });
  row.addEventListener("mouseleave", hideTip);
}
document.addEventListener("scroll", hideTip, true);

// --- strona hasła ------------------------------------------------------------------------------------------------

async function openEntry(name) {
  hideTip();
  if (!(await leaveEntry())) return;
  collectDrafts();
  camp.entry = name;
  $("#view").scrollTop = 0;
  await renderCampaigns();
}

// Zapisuje opis przed opuszczeniem strony; false = nie udało się zapisać (zostajemy, żeby tekst nie przepadł)
async function saveEntry() {
  const text = $("#entry-text");
  if (!camp.entry || !text || text.value.trim() === text.dataset.base.trim()) return true;
  try {
    await api("/api/campaign", { key: camp.key, what: "description", name: camp.entry, value: text.value });
    draftSaved(text);
    toast(`Zapisano opis: ${camp.entry}`);
    return true;
  } catch (e) { toast(e.message); return false; }
}

async function leaveEntry() {
  if (!camp.entry) return true;
  if (!(await saveEntry()) && !(await confirmDiscard("Nie udało się zapisać opisu hasła."))) return false;
  const text = $("#entry-text");
  if (text) { text.value = text.dataset.base; camp.drafts.delete(text.dataset.draft); }   // zapisane albo porzucone
  camp.entry = null;
  camp.entryData = null;
  return true;
}

function entryPage() {
  const x = camp.entryData;
  const text = draftField(el("textarea", { id: "entry-text" }), `entry/${x.name}`, x.description);
  text.style.minHeight = "160px";
  const image = async (action) => {
    try { await api("/api/entry/image", { key: camp.key, name: x.name, action }); await renderCampaigns(); } catch (e) { toast(e.message); }
  };
  const pick = el("input", { type: "file", accept: ".jpg,.jpeg,.png,.webp", hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      await api("/api/entry/upload", { key: camp.key, name: x.name, filename: file.name, data: await fileBase64(file) });
      await renderCampaigns();
    } catch (err) { toast(err.message); }
  } });
  const generate = (label, cls) => button(label, () => imageDialog(x), cls, { "data-task": true, disabled: state.running,
    title: "AI narysuje obrazek z opisu w stylu kampanii (Cloudflare FLUX, darmowy limit dzienny). Najpierw zobaczysz propozycję." });
  let picture;
  if (x.proposal) {
    picture = [el("div", { class: "hint" }, "Propozycja AI - jeszcze nie zapisana"),
      el("img", { class: "entry-image", src: imageUrl(x.name, x.proposal, true), alt: x.name, title: x.proposal_prompt || null }),
      el("div", { class: "actions center" }, button("Zachowaj", () => image("keep"), "btn suggested"),
         x.can_generate ? generate("Spróbuj ponownie…", "btn") : null, button("Odrzuć", () => image("discard"), "btn flat"))];
  } else {
    picture = [x.image ? el("img", { class: "entry-image", src: imageUrl(x.name, x.image), alt: x.name }) : null,
      el("div", { class: "actions center" }, pick,
         button(x.image ? "Zmień zdjęcie…" : "Dodaj zdjęcie…", () => pick.click(), "btn", { title: "JPG, PNG albo WebP - kopia trafi do folderu kampanii (i na Drive)" }),
         x.can_generate ? generate("Wygeneruj obrazek (AI)…", "btn") : null,
         x.image ? button("Usuń zdjęcie", async () => {
           const answer = await ask("Usunąć zdjęcie?", `Zdjęcie hasła „${x.name}” zostanie usunięte z folderu kampanii.`,
                                    [["cancel", "Anuluj"], ["remove", "Usuń", "destructive"]]);
           if (answer === "remove") image("remove");
         }, "btn flat") : null)];
  }
  return [
    el("div", { class: "entry-head" }, button("← Wróć", async () => { if (await leaveEntry()) renderCampaigns(); }, "btn flat"),
       el("h2", {}, x.name), el("span", { class: "hint" }, x.category)),
    groupBox("Zdjęcie", "", el("div", { class: "entry-picture" }, picture)),
    groupBox("Opis", "Krótko: kto to albo co to jest, rola w historii, stosunek do drużyny. Trafia do encyklopedii kampanii. "
             + "Zapisuje się przy wyjściu ze strony.", text),
  ];
}

function fileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("Nie można odczytać pliku"));
    reader.readAsDataURL(file);
  });
}

function imageDialog(x) {
  const hints = el("textarea", { placeholder: "np. rude włosy, blizna na policzku, w deszczu, nocą" });
  hints.value = x.hints;
  const run = async () => {
    if (!(await saveEntry())) return;   // zadanie czyta opis z kampanie.toml
    dialog.close();
    const text = hints.value.replace(/\s+/g, " ").trim();
    startTask(`Obrazek: ${x.name}`, ["image", camp.key, x.name, ...providerArgs(), ...(text ? [`--wskazowki=${text}`] : [])]);
  };
  const dialog = openDialog(`Obrazek: ${x.name}`, el("div", { class: "field" }, el("div", { class: "hint" },
    "AI narysuje go z opisu hasła i stylu kampanii. Możesz dopisać, co ma być na obrazku. Pisz po polsku, AI przetłumaczy; wskazówki mają "
    + "pierwszeństwo przed opisem. Puste pole = tylko opis hasła."), hints),
    { footer: [button("Anuluj", () => dialog.close()), button("Wygeneruj", run, "btn suggested", { "data-task": true, disabled: state.running })] });
  hints.focus();
}

// --- Przed sesją -------------------------------------------------------------------------------------------------

function prepGroup() {
  const c = camp.data;
  // Bez kronik nie ma z czego pisać: przycisk zostaje nieaktywny (bez data-task, które włącza go po zadaniu)
  const write = (label, title, args, done, tooltip) => c.has_chronicles
    ? campaignTask(label, title, args, done ? "btn flat" : "btn suggested", tooltip)
    : button(label, () => {}, "btn", { disabled: true, title: "Najpierw potrzebna jest kronika" });
  const block = (title, status, buttons, content, id) => {
    const head = el("div", { class: "row" }, el("div", { class: "label" }, title, el("div", { class: "hint" }, status)), buttons);
    if (!content) return head;
    return el("div", { class: "prep" }, head, el("details", { open: camp.expanded.has(id),
      ontoggle: (e) => { if (e.target.open) camp.expanded.add(id); else camp.expanded.delete(id); } },
      el("summary", {}, "Pokaż"), content));
  };
  const send = c.recap.text && c.webhook ? button("Na Discord", async () => {
    const answer = await ask(`Wysłać „${c.recap.title}” na Discord?`, `Tekst trafi na kanał kampanii ${c.key} - zobaczą go gracze.`,
                             [["cancel", "Anuluj"], ["send", "Wyślij", "suggested"]]);
    if (answer === "send") startTask(`Poprzednio w kampanii ${c.key} → Discord`, ["recap", c.key, "--discord", ...providerArgs()]);
  }, "btn flat", { "data-task": true, disabled: state.running, title: "Wyślij na kanał Discord kampanii (przed sesją)" }) : null;
  const rows = el("div", { class: "rows" },
    block(c.recap.title, c.recap.status, [send, write(c.recap.text ? "Odśwież" : "Napisz", `Poprzednio w kampanii ${c.key}`,
      ["recap", c.key, "--force"], c.recap.text, "AI napisze tekst z ostatniej kroniki i otwartych wątków (1–2 min czytania)")],
      c.recap.text ? el("div", { class: "pre" }, c.recap.text) : null, "recap"),
    block(c.ideas.title, c.ideas.status, [write(c.ideas.html ? "Nowe pomysły" : "Wymyśl", `Pomysły na sesję ${c.key}`, ["ideas", c.key], c.ideas.html,
      c.ideas.html ? "AI zaproponuje nowe pomysły (inne niż obecne)" : `AI zaproponuje ${c.ideas.count} pomysłów na wydarzenia najbliższej sesji`)],
      c.ideas.html ? el("div", { class: "chronicle", html: c.ideas.html }) : null, "ideas"),
    block("Notatki MG", c.gm_notes.status, [
      c.gm_notes.path ? button("Otwórz PDF", () => openFile(c.gm_notes.path), "btn flat", { title: "Tylko dla MG - nie trafia na Discord" }) : null,
      write(c.gm_notes.path ? "Odśwież" : "Utwórz", `Notatki MG ${c.key}`, ["gm-notes", c.key], c.gm_notes.path, "AI przejrzy wszystkie kroniki i stan kampanii")],
      null, "gm-notes"));
  return groupBox("Przed sesją", "Na początek kolejnej sesji: tekst do przeczytania graczom na głos, pomysły na wydarzenia i ściągawka dla MG "
    + "(otwarte wątki, obietnice, niewykorzystane tropy, BN-i). Pisze je AI z kronik.", rows);
}

function askGroup() {
  const c = camp.data;
  const input = draftField(el("input", { type: "text", class: "grow", disabled: !c.has_chronicles,
    placeholder: c.has_chronicles ? "Twoje pytanie" : "Najpierw potrzebna jest kronika" }), "ask", "");
  const send = () => {
    const question = input.value.trim();
    if (!question || state.running) return;
    input.value = "";
    startTask(`Pytanie do kronikarza (${c.key})`, ["ask", c.key, ...providerArgs(), "--", question]);
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  const askButton = c.has_chronicles ? button("Zapytaj", send, "btn suggested", { "data-task": true, disabled: state.running })
                                     : button("Zapytaj", () => {}, "btn", { disabled: true });
  const rows = el("div", { class: "rows" }, el("div", { class: "row" }, input, askButton),
    c.history.map((h, i) => el("details", { class: "answer", open: i === 0 },
      el("summary", {}, el("b", {}, h.question), el("span", { class: "hint" }, ` ${h.when}`)),
      el("div", { class: "chronicle", html: h.html }),
      el("div", { class: "actions start" }, h.sessions.map((name) => button(name, () => openSessionChronicle(name), "btn", { title: "Przejdź do kroniki tej sesji" })),
         el("span", { class: "grow" }), removeButton("Usuń z historii", async () => {
           try { await api("/api/campaign/forget", { key: c.key, question: h.question, asked: h.asked }); renderCampaigns(); } catch (e) { toast(e.message); }
         })))));
  return groupBox("Zapytaj kronikarza", "Pytanie o kampanię, np. „Kiedy poznaliśmy Ojca Romulusa?” albo „Komu jesteśmy winni pieniądze?”. AI odpowie "
    + "z kronik i stanu kampanii i wskaże sesje.", rows);
}

async function openSessionChronicle(name) {
  state.tab = "kronika";
  state.mode = "kronika";
  await showMain("sesje");
  await loadSession(name, false);
}

// --- Dokumenty -----------------------------------------------------------------------------------------------------

function documentRow(title, file, status, build) {
  return el("div", { class: "row" }, el("div", { class: "label" }, title, el("div", { class: "hint" }, status)),
    file.path ? button("Otwórz PDF", () => openFile(file.path), "btn flat") : null, build);
}

function encyclopediaGroup() {
  const c = camp.data, e = c.encyclopedia;
  return groupBox("Encyklopedia kampanii", "PDF dla graczy: oś czasu sesji, stan kampanii oraz postacie, miejsca i przedmioty z opisami (AI) i listą "
    + "sesji, w których się pojawiły. Leży obok kronik, więc trafia też na Drive.",
    el("div", { class: "rows" }, documentRow(e.name, e, e.path ? `utworzona ${e.date}` : "jeszcze nie ma",
      campaignTask(e.path ? "Odśwież" : "Utwórz", `Encyklopedia kampanii ${c.key}`, ["encyclopedia", c.key], e.path ? "btn" : "btn suggested",
                   "AI przeczyta kroniki tej kampanii i opisze hasła (kilka minut)"))));
}

function diariesGroup() {
  const c = camp.data;
  return groupBox("Dzienniki postaci", "PDF dla gracza: wydarzenia kampanii opowiedziane przez jego postać, wpis po każdej sesji (AI, z kronik). "
    + "Odświeżenie po nowej sesji dopisuje tylko nowe wpisy.",
    el("div", { class: "rows" }, c.diaries.length
      ? c.diaries.map((d) => documentRow(d.character, d, d.path ? `utworzony ${d.date}` : "jeszcze nie ma",
          campaignTask(d.path ? "Odśwież" : "Utwórz", `Dziennik postaci ${d.character}`, ["diary", c.key, d.character], "btn",
                       `AI opisze kolejne sesje z perspektywy postaci ${d.character}`)))
      : el("div", { class: "row" }, el("div", { class: "label hint" }, "Najpierw dodaj postacie graczy (zakładka Słownik)"))));
}
