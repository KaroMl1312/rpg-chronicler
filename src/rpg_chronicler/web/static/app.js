// RPG Chronicles - nowe okno (etap 1): sesje, transkrypcja, kronika, zadania, ustawienia, nowości.
// Zwykły JavaScript bez bibliotek; dane z lokalnego serwera (web/server.py), klucz okna z adresu (#t=...).
"use strict";

const HASH = new URLSearchParams(location.hash.slice(1));
const TOKEN = HASH.get("t") || "";
const $ = (sel, root = document) => root.querySelector(sel);

const ICONS = {
  menu: '<svg viewBox="0 0 16 16"><path d="M1 3h14v2H1zm0 4h14v2H1zm0 4h14v2H1z"/></svg>',
  check: '<svg viewBox="0 0 16 16"><path d="M6.2 11.2 2.9 7.9 1.5 9.3l4.7 4.7 8.3-8.3-1.4-1.4z"/></svg>',
  send: '<svg viewBox="0 0 16 16"><path d="M1 14.5 15 8 1 1.5V6.5l9 1.5-9 1.5z"/></svg>',
  more: '<svg viewBox="0 0 16 16"><circle cx="8" cy="3" r="1.6"/><circle cx="8" cy="8" r="1.6"/><circle cx="8" cy="13" r="1.6"/></svg>',
  play: '<svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z"/></svg>',
  stop: '<svg viewBox="0 0 16 16"><rect x="3.5" y="3.5" width="9" height="9" rx="1"/></svg>',
  search: '<svg viewBox="0 0 16 16"><path d="M6.5 1a5.5 5.5 0 0 1 4.4 8.8l3.7 3.7-1.4 1.4-3.7-3.7A5.5 5.5 0 1 1 6.5 1zm0 2a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"/></svg>',
  plus: '<svg viewBox="0 0 16 16"><path d="M7 2h2v5h5v2H9v5H7V9H2V7h5z"/></svg>',
  trash: '<svg viewBox="0 0 16 16"><path d="M6 1h4l1 1h3v2H2V2h3zM3 5h10l-.8 10H3.8zm3 2v6h1V7zm3 0v6h1V7z"/></svg>',
  next: '<svg viewBox="0 0 16 16"><path d="M5.5 2 11.5 8l-6 6-1.4-1.4L8.7 8 4.1 3.4z"/></svg>',
  close: '<svg viewBox="0 0 16 16"><path d="M3.5 2.1 8 6.6l4.5-4.5 1.4 1.4L9.4 8l4.5 4.5-1.4 1.4L8 9.4l-4.5 4.5-1.4-1.4L6.6 8 2.1 3.5z"/></svg>',
};

const state = {
  data: null,          // /api/state
  main: "sesje",       // sesje / kampanie
  filter: null,        // klucz kampanii albo null = wszystkie
  current: null,       // nazwa wybranej sesji
  detail: null,        // /api/session
  tab: "kronika",
  mode: "kronika",     // kronika / skrot / cytaty
  seq: 0,              // ostatnia linia logu
  finishedSeq: 0,
  log: [],
  running: false,
};

// --- pomocnicze -----------------------------------------------------------------------------

async function api(path, body) {
  const options = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function button(label, onclick, cls = "btn", attrs = {}) {
  return el("button", { class: cls, onclick, ...attrs }, label);
}

function iconButton(icon, title, onclick) {
  return el("button", { class: "btn flat icon", title, onclick, html: ICONS[icon] });
}

function toast(text, action, onAction) {
  const node = el("div", { class: "toast" }, el("span", {}, text));
  if (action) node.append(button(action, () => { node.remove(); onAction(); }, ""));
  $("#toasts").append(node);
  const plain = [...document.querySelectorAll(".toast")].filter((t) => !t.querySelector("button"));
  for (const old of plain.slice(0, -2)) old.remove();   // najwyżej dwa zwykłe naraz; te z przyciskiem zostają
  setTimeout(() => node.remove(), action ? 12000 : 5000);
}

function formatDuration(seconds) {
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : m ? `${m} min ${String(s).padStart(2, "0")} s` : `${s} s`;
}

// --- okna dialogowe i menu --------------------------------------------------------------------

function openDialog(title, body, { footer = [], cls = "", onclose } = {}) {
  const dialog = el("dialog", { class: cls });
  const close = () => dialog.close();
  dialog.append(el("div", { class: "dlg" },
    title ? el("div", { class: "dlg-head" }, el("span", { class: "grow" }, title), iconButton("close", "Zamknij", close))
          : null,
    el("div", { class: "dlg-body" }, body),
    footer.length ? el("div", { class: "dlg-foot" }, footer) : null));
  dialog.addEventListener("close", () => { dialog.remove(); if (onclose) onclose(); });
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

// Pytanie z kilkoma odpowiedziami; zwraca klucz wybranej (albo null po zamknięciu).
function ask(heading, text, responses) {
  return new Promise((resolve) => {
    let answer = null;
    const footer = responses.map(([key, label, style]) =>
      button(label, () => { answer = key; dialog.close(); }, `btn ${style || ""}`));
    const dialog = openDialog(null, [el("h3", {}, heading), el("div", {}, text)],
                              { footer, cls: "alert", onclose: () => resolve(answer) });
  });
}

// Nie udało się zapisać: zostać czy porzucić wpisane zmiany (true = porzuć)
async function confirmDiscard(text) {
  const answer = await ask("Zmiany nie są zapisane", `${text} Porzucić je?`,
                           [["stay", "Zostań"], ["drop", "Porzuć zmiany", "destructive"]]);
  return answer === "drop";
}

let openPopover = null;
function closePopover() { if (openPopover) { openPopover.remove(); openPopover = null; } }
document.addEventListener("click", (e) => { if (openPopover && !openPopover.contains(e.target)) closePopover(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePopover(); });

// items: [{label, onclick, disabled, checked}] | "-" | {section: "tytuł"}
function popover(anchor, items) {
  closePopover();
  const node = el("div", { class: "popover" });
  for (const item of items) {
    if (item === "-") node.append(el("div", { class: "sep" }));
    else if (item.section) node.append(el("div", { class: "label" }, item.section));
    else node.append(el("button", {
      disabled: item.disabled, onclick: (e) => { e.stopPropagation(); closePopover(); item.onclick(); },
    }, item.checked !== undefined ? el("span", { class: "check" }, item.checked ? "✓" : "") : null, item.label));
  }
  document.body.append(node);
  const rect = anchor.getBoundingClientRect();
  const width = node.offsetWidth;
  node.style.top = `${rect.bottom + 4}px`;
  node.style.left = `${Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8))}px`;
  openPopover = node;
}

// --- zadania ------------------------------------------------------------------------------------

function providerArgs() { return ["--provider", state.data.provider]; }

async function startTask(title, args) {
  try {
    const result = await api("/api/task", { title, args });
    if (result.error) return toast(result.error);
    pollTask();
  } catch (e) { toast(e.message); }
}

async function pollTask() {
  let task;
  try { task = await api(`/api/task?since=${state.seq}`); } catch { return; }
  state.seq = task.seq;
  state.log.push(...task.lines);
  if (state.log.length > 5000) state.log.splice(0, state.log.length - 5000);
  const logView = $("#log-view");
  if (logView) { logView.textContent = state.log.join("\n"); logView.parentElement.scrollTop = 1e9; }

  const wasRunning = state.running;
  state.running = task.running;
  $("#taskbar").hidden = !task.running;
  if (task.running) {
    $("#task-title").textContent = task.title;
    const p = task.progress;
    const parts = [];
    if (p) parts.push([p.stage, p.session].filter(Boolean).join(" · "));
    if (task.status) parts.push(task.status);
    parts.push(formatDuration(task.elapsed) + (task.remaining ? `, zostało ok. ${formatDuration(task.remaining)}` : ""));
    $("#task-stage").textContent = parts.filter(Boolean).join(" — ");
    const bar = $("#task-progress");
    const known = p && p.fraction !== null && p.fraction !== undefined;
    bar.classList.toggle("pulse", !known);
    bar.firstElementChild.style.width = known ? `${Math.round(p.fraction * 100)}%` : "";
  }
  if (task.finished && task.finished.seq > state.finishedSeq) {
    const first = state.finishedSeq === 0 && !wasRunning;   // zakończenie sprzed otwarcia okna - bez powiadomienia
    state.finishedSeq = task.finished.seq;
    if (!first) {
      const f = task.finished;
      toast(`${f.title}: ${f.description}`, f.success ? null : "Pokaż log", showLog);
      for (const p of f.proposals || []) toast(p.text, "Przejrzyj", () => showCampaign(p.campaign, p.text.includes("słownika") ? "slownik" : "ogolne"));
      await refresh();
    }
  }
  updateTaskButtons();
  if (task.running) setTimeout(pollTask, 600);
}

function updateTaskButtons() {
  for (const node of document.querySelectorAll("[data-task]")) node.disabled = state.running;
}

function taskButton(label, title, args, cls = "btn", tooltip) {
  return button(label, () => startTask(title, args), cls, { "data-task": true, title: tooltip, disabled: state.running });
}

function showLog() {
  const pre = el("pre", { class: "log", id: "log-view" }, state.log.join("\n") || "Log jest pusty.");
  const dialog = openDialog("Log zadań", pre);
  dialog.querySelector(".dlg-body").scrollTop = 1e9;
}

// --- lista sesji ------------------------------------------------------------------------------

async function refresh() {
  state.data = await api("/api/state");
  renderFilter();
  renderList();
  if (state.current && !state.data.sessions.some((s) => s.name === state.current)) {   // sesja usunięta
    state.current = null;
    forgetSpeakers();
  }
  if (state.main === "kampanie") return renderCampaigns();
  if (state.current) await loadSession(state.current, false);
  else renderEmpty();
}

function renderFilter() {
  const select = $("#filter");
  select.replaceChildren(...state.data.filters.map((f) =>
    el("option", { value: f.key ?? "*", selected: (f.key ?? null) === state.filter }, f.label)));
}

function visibleSessions() {
  return state.data.sessions.filter((s) => state.filter === null || s.campaign === state.filter);
}

function renderList() {
  const list = $("#session-list");
  list.replaceChildren(...visibleSessions().map((s) => {
    let discord = null;
    if (s.discord) {
      const old = s.discord !== "wyslano";
      discord = el("span", { class: `icon ${old ? "state-old" : "state-sent"}`,
                             title: old ? "Na Discordzie starsza wersja kroniki" : "Wysłano na Discord",
                             html: ICONS.send });
    }
    return el("li", { class: s.name === state.current ? "active" : "", onclick: () => loadSession(s.name) },
      el("div", { class: "names" }, el("div", { class: "name" }, s.name),
         el("div", { class: "sub" }, [s.campaign || "bez kampanii", s.stage].join(" · "))),
      discord,
      s.done ? el("span", { class: "icon state-ok", title: "Gotowe", html: ICONS.check }) : null);
  }));
}

function renderEmpty() {
  $("#campaign-tabs").hidden = true;
  $("#session-name").textContent = "";
  $("#session-tabs").hidden = true;
  $("#header-right").replaceChildren();
  $("#toolbar").hidden = true;
  const count = state.data.sessions.length;
  $("#view").replaceChildren(el("div", { class: "empty" },
    el("h2", {}, count ? "Wybierz sesję" : "Nie ma jeszcze sesji"),
    el("div", {}, count ? "Kliknij sesję na liście po lewej."
                        : `Wrzuć nagranie do folderu ${state.data.folders.nagrania} (nazwa: Kampania_RRMMDD) `
                          + "i kliknij „Przetwórz wszystko”.")));
}

// --- sesja ----------------------------------------------------------------------------------------

async function loadSession(name, resetMode = true) {
  if (state.current !== name) {
    if (!(await autosaveSpeakers())) return;
    stopPlayback();
    if (resetMode) state.mode = "kronika";
  }
  state.current = name;
  renderList();
  let detail;
  try { detail = await api(`/api/session?name=${encodeURIComponent(name)}`); } catch (e) { return toast(e.message); }
  if (state.current !== name) return;   // w międzyczasie wybrano inną sesję
  state.detail = detail;
  if (state.main === "sesje") renderSession();
}

let keepScroll = 0;

function renderSession() {
  const d = state.detail;
  $("#session-name").textContent = d.name;
  $("#session-tabs").hidden = false;
  $("#campaign-tabs").hidden = true;
  const view = $("#view");
  const place = `${d.name}/${state.tab}/${state.mode}`;   // odświeżenie tego samego widoku nie przewija do góry
  keepScroll = view.dataset.place === place ? view.scrollTop : 0;
  view.dataset.place = place;
  const transcriptTab = $('#session-tabs [data-tab="transkrypcja"]');
  transcriptTab.textContent = d.from_notes ? "Notatki" : "Transkrypcja";
  $('#session-tabs [data-tab="mowcy"]').hidden = d.from_notes;
  if (d.from_notes && state.tab === "mowcy") state.tab = "transkrypcja";
  for (const b of document.querySelectorAll("#session-tabs button")) b.classList.toggle("active", b.dataset.tab === state.tab);
  $("#header-right").replaceChildren(
    d.campaign ? button(`Kampania ${d.campaign}`, () => showCampaign(d.campaign), "btn flat", { title: "Otwórz kampanię" }) : "",
    iconButton("more", "Notatki i usuwanie sesji", sessionMenu));
  if (state.tab === "transkrypcja") renderTranscript();
  else if (state.tab === "mowcy") renderSpeakers();
  else renderChronicle();
}

async function renderTranscript() {
  const d = state.detail;
  const toolbar = $("#toolbar");
  toolbar.hidden = true;
  if (!d.has_transcript && !d.has_notes) {
    $("#view").replaceChildren(el("div", { class: "empty" },
      el("h2", {}, d.audio ? "Nagranie czeka na transkrypcję" : "Brak nagrania"),
      el("div", {}, d.audio ? "Transkrypcja trwa zwykle ok. 1/4 długości nagrania." : ""),
      d.audio ? taskButton("Transkrybuj", `Transkrypcja ${d.name}`, ["transcribe", d.name], "btn suggested") : null));
    return;
  }
  const scroll = keepScroll;
  if (!scroll) $("#view").replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
  let t;
  try { t = await api(`/api/transcript?name=${encodeURIComponent(d.name)}`); } catch (e) { return toast(e.message); }
  if (state.detail !== d || state.tab !== "transkrypcja" || state.main !== "sesje") return;
  if (t.kind === "notatki") {
    toolbar.hidden = false;
    toolbar.replaceChildren(el("span", { class: "info" },
      t.present.length ? `Obecni: ${t.present.join(", ")}` : "Notatki Mistrza Gry"));
    $("#view").replaceChildren(el("div", { class: "page chronicle", html: t.html }));
    return;
  }
  const page = el("div", { class: "page" });
  // Długie transkrypcje (tysiące wypowiedzi) dokładamy partiami, żeby okno nie zamarło
  let index = 0, scrolled = false;
  const addChunk = () => {
    const fragment = document.createDocumentFragment();
    for (const b of t.blocks.slice(index, index + 400)) {
      fragment.append(el("div", { class: "utterance" }, el("span", { class: "time" }, b.time),
        el("div", {}, b.speaker ? el("span", { class: `speaker mowca-${b.color}` }, b.speaker) : null, b.text)));
    }
    page.append(fragment);
    index += 400;
    if (scroll && page.isConnected && page.offsetHeight > scroll && !scrolled) { $("#view").scrollTop = scroll; scrolled = true; }
    if (index < t.blocks.length && (page.isConnected || index <= 400)) requestAnimationFrame(addChunk);
  };
  $("#view").replaceChildren(page);
  addChunk();
}

function renderChronicle() {
  const d = state.detail;
  const toolbar = $("#toolbar");
  if (!d.has_summary) {
    toolbar.hidden = true;
    const ready = d.has_transcript || d.has_notes;
    $("#view").replaceChildren(el("div", { class: "empty" },
      el("h2", {}, "Kronika jeszcze nie powstała"),
      el("div", {}, ready ? "AI napisze kronikę sesji na podstawie " + (d.from_notes ? "notatek MG." : "transkrypcji.")
                          : "Najpierw potrzebna jest transkrypcja nagrania."),
      ready ? button("Napisz kronikę", () => summarize(false), "btn suggested", { "data-task": true, disabled: state.running })
            : null));
    return;
  }
  toolbar.hidden = false;
  const modes = el("div", { class: "switcher" }, [["kronika", "Kronika"], ["skrot", "Skrót"], ["cytaty", "Cytaty"]]
    .filter(([key]) => key !== "cytaty" || !d.from_notes)
    .map(([key, label]) => el("button", { class: state.mode === key ? "active" : "",
                                          onclick: () => { state.mode = key; renderSession(); } }, label)));
  const pdfButton = d.pdf_current
    ? button("PDF", () => api("/api/open-session-file", { name: d.name, kind: "pdf" }).catch((e) => toast(e.message)),
             "btn", { title: "Otwórz PDF kroniki" })
    : taskButton("PDF", `PDF ${d.name}`, ["pdf", d.name], "btn", d.pdf ? "PDF jest nieaktualny - utwórz go od nowa" : "Utwórz PDF kroniki");
  const revise = button("Popraw…", reviseDialog, "btn", { "data-task": true, disabled: state.running,
                                                          title: "Popraw kronikę poleceniem dla AI" });
  const discordButton = button("Wyślij na Discord", discordDialog, "btn", { title: d.discord_label || "Wyślij kronikę na kanał kampanii" });
  const more = iconButton("more", "Więcej", (e) => {
    e.stopPropagation();
    popover(e.currentTarget, [
      d.previous_versions ? { label: "Cofnij poprawkę", onclick: undoRevision, disabled: state.running } : null,
      { label: "Napisz kronikę ponownie", onclick: () => summarize(true), disabled: state.running },
      { label: "Napisz skrót ponownie", disabled: state.running,
        onclick: () => startTask(`Skrót kroniki ${d.name}`, ["brief", d.name, ...providerArgs(), "--force"]) },
      d.from_notes ? null : { label: "Wybierz cytaty ponownie", disabled: state.running,
        onclick: () => startTask(`Cytaty z sesji ${d.name}`, ["quotes", d.name, ...providerArgs(), "--force"]) },
      "-",
      { label: d.discord ? "Oznacz jako niewysłaną" : "Oznacz jako wysłaną na Discord", onclick: toggleSent },
      { label: "Otwórz plik kroniki", onclick: () => api("/api/open-session-file", { name: d.name, kind: "kronika" })
          .catch((err) => toast(err.message)) },
    ].filter(Boolean));
  });
  toolbar.replaceChildren(modes, el("span", { class: "info", title: d.info }, d.info), revise, pdfButton, discordButton, more);

  const page = el("div", { class: "page chronicle" });
  if (state.mode === "kronika") {
    page.innerHTML = d.chronicle_html;
  } else if (state.mode === "skrot") {
    if (d.brief_html) {
      if (!d.brief_current) page.append(el("div", { class: "notice warn" }, "Kronika zmieniła się po napisaniu skrótu."));
      page.append(el("div", { html: d.brief_html }));
    } else {
      page.append(el("div", { class: "empty" }, el("h2", {}, "Brak skrótu"),
        taskButton("Napisz skrót", `Skrót kroniki ${d.name}`, ["brief", d.name, ...providerArgs()], "btn suggested")));
    }
  } else if (d.quotes.length) {
    page.append(...d.quotes.map((q, i) => el("div", { class: "quote" }, quotePlayButton(d, q, i),
      el("div", { class: "body" }, `„${q.text}”`, el("div", { class: "who" }, [q.who, q.time].filter(Boolean).join(" · "))))));
  } else {
    page.append(el("div", { class: "empty" }, el("h2", {}, "Brak cytatów"),
      taskButton("Wybierz cytaty", `Cytaty z sesji ${d.name}`, ["quotes", d.name, ...providerArgs()], "btn suggested")));
  }
  $("#view").replaceChildren(page);
  $("#view").scrollTop = keepScroll;
}

async function summarize(force) {
  if (speakersState.name) {   // niezapisane imiona mówców - zapis przed kroniką
    if (!(await autosaveSpeakers())) return;
    await loadSession(state.current, false);
  }
  const d = state.detail;
  let allowUnnamed = false;
  if (d.unnamed_speakers) {
    const answer = await ask("Mówcy nie mają imion",
      "Kronika powstanie z etykietami SPEAKER_00, SPEAKER_01… zamiast imion postaci. Lepiej najpierw nazwać mówców "
      + "w zakładce „Mówcy”.",
      [["cancel", "Anuluj"], ["speakers", "Nazwij mówców", "suggested"], ["generate", "Generuj mimo to"]]);
    if (answer === "speakers") { state.tab = "mowcy"; renderSession(); return; }
    if (answer !== "generate") return;
    allowUnnamed = true;
  } else if (force) {
    const answer = await ask("Wygenerować kronikę ponownie?", "Obecna kronika zostanie zastąpiona nową wersją.",
                             [["cancel", "Anuluj"], ["generate", "Generuj ponownie", "destructive"]]);
    if (answer !== "generate") return;
  }
  if (d.memory_warning) {
    const answer = await ask("Stan kampanii czeka na zatwierdzenie",
      `${d.memory_warning}\n\nZatwierdź propozycję w zakładce „Kampanie”, żeby kronika znała najnowszy stan świata.`,
      [["cancel", "Anuluj"], ["generate", "Generuj mimo to"], ["campaigns", "Otwórz Kampanie", "suggested"]]);
    if (answer === "campaigns") return showCampaign(d.campaign, "ogolne");
    if (answer !== "generate") return;
  }
  const args = ["summarize", "--no-interactive", ...providerArgs()];
  if (allowUnnamed) args.push("--allow-unnamed");
  if (force) args.push("--force");
  startTask(`Kronika ${d.name}`, [...args, d.name]);
}

// --- Sesje / Kampanie (widok kampanii: kampanie.js) ---------------------------------------------------

// false, gdy nie udało się zapisać wpisanych zmian i użytkownik woli zostać
async function showMain(name) {
  if (!(await autosaveSpeakers()) || !(await leaveEntry())) return false;
  stopPlayback();
  hideTip();
  collectDrafts();
  state.main = name;
  for (const b of document.querySelectorAll("#main-switch button")) b.classList.toggle("active", b.dataset.main === name);
  const sessions = name === "sesje";
  for (const id of ["#session-tools", "#session-list", "#session-foot"]) $(id).hidden = !sessions;
  for (const id of ["#campaign-list", "#campaign-foot"]) $(id).hidden = sessions;
  await refresh();
  return true;
}

// Zamykanie okna (wołają je okno_gtk.py i __main__.py): zapisuje wpisane zmiany i pyta, gdy coś by przepadło.
// true = można zamknąć. Trwające zadanie przerywa serwer po zamknięciu okna.
async function confirmClose() {
  try {
    if (!(await saveSpeakerEdits())) return false;
    if (!(await saveEntry()) && !(await confirmDiscard("Nie udało się zapisać opisu hasła."))) return false;
    if (unsavedTexts() && !(await confirmDiscard("Masz niezapisany tekst w zakładce Kampanie."))) return false;
    const task = await api("/api/task?since=" + Number.MAX_SAFE_INTEGER);
    if (task.running) {
      const answer = await ask("Zadanie jest w toku", `„${task.title}” zostanie przerwane. Zamknąć mimo to?`,
                               [["cancel", "Nie zamykaj"], ["close", "Przerwij i zamknij", "destructive"]]);
      return answer === "close";
    }
  } catch { /* serwer nie odpowiada - nie ma czego zapisać, okno można zamknąć */ }
  return true;
}

function unsavedTexts() {
  collectDrafts();
  return [...camp.drafts.values()].some((d) => d.long);
}

// --- menu główne, ustawienia, nowości -----------------------------------------------------------

function mainMenu(e) {
  e.stopPropagation();
  const p = state.data.provider;
  popover(e.currentTarget, [
    { label: "Odśwież listę", onclick: refresh },
    { label: "Pobierz z Google Drive", onclick: () => startTask("Pobieranie z Google Drive", ["sync"]), disabled: state.running },
    { label: "Wyślij na Google Drive", onclick: () => startTask("Wysyłanie na Google Drive", ["upload"]), disabled: state.running },
    { label: "Przetwórz bez Google Drive", disabled: state.running,
      onclick: () => startTask("Przebieg bez Google Drive", ["run", "--offline", "--no-interactive", ...providerArgs()]) },
    { section: "Dostawca AI" },
    ...state.data.providers.map((x) => ({ label: x.label, checked: x.key === p, onclick: () => setProvider(x.key) })),
    "-",
    { label: "Ustawienia", onclick: showSettings },
    { label: "Pokaż log", onclick: showLog },
    { label: `Nowości (wersja ${state.data.version})`, onclick: showChangelog },
  ]);
}

async function setProvider(key) {
  try { await api("/api/settings", { key: "ai.dostawca", value: key }); } catch (e) { return toast(e.message); }
  state.data.provider = key;
  if (state.current) loadSession(state.current, false);
}

async function showChangelog() {
  const data = await api("/api/changelog");
  openDialog(`Nowości – wersja ${data.version}`, el("div", { class: "chronicle", html: data.html }));
}

async function showSettings() {
  const data = await api("/api/settings");
  const pages = { ogolne: el("div"), klucze: el("div") };
  for (const group of data.groups) pages.ogolne.append(settingsGroup(group));
  pages.klucze.append(el("div", { class: "notice" },
    `Klucze zapisują się tylko na tym komputerze, w pliku ${data.env_path}. Wklej klucz i naciśnij „Zapisz”.`));
  for (const service of data.keys) pages.klucze.append(keysGroup(service));
  pages.klucze.hidden = true;
  const tabs = el("div", { class: "switcher settings-tabs" },
    [["ogolne", "Ogólne"], ["klucze", "Klucze API"]].map(([key, label], i) => el("button", {
      class: i === 0 ? "active" : "",
      onclick: (e) => {
        for (const b of tabs.children) b.classList.toggle("active", b === e.currentTarget);
        for (const [k, node] of Object.entries(pages)) node.hidden = k !== key;
      } }, label)));
  openDialog("Ustawienia", [tabs, pages.ogolne, pages.klucze], { onclose: refresh });
}

async function saveSetting(key, value) {
  try { await api("/api/settings", { key, value }); toast("Zapisano"); }
  catch (e) { toast(e.message); }
}

function settingsGroup(group) {
  const rows = el("div", { class: "rows" });
  for (const f of group.fields) {
    let input;
    if (f.kind === "bool") {
      const box = el("input", { type: "checkbox", checked: !!f.value, onchange: (e) => saveSetting(f.key, e.target.checked) });
      input = el("label", { class: "switch" }, box, el("span"));
    } else if (f.kind === "choice") {
      input = el("select", { onchange: (e) => saveSetting(f.key, e.target.value) },
        f.options.map((o) => el("option", { value: o.key, selected: o.key === f.value }, o.label)));
    } else if (f.kind === "int") {
      input = el("input", { type: "number", min: 1, value: f.value, onchange: (e) => saveSetting(f.key, e.target.value) });
    } else {
      input = el("input", { type: "text", value: f.value, onchange: (e) => saveSetting(f.key, e.target.value) });
    }
    rows.append(el("div", { class: "row" },
      el("div", { class: "label" }, f.label, f.hint ? el("div", { class: "hint" }, f.hint) : null), input));
  }
  return el("div", { class: "group" }, el("h3", {}, group.title),
            group.description ? el("div", { class: "desc" }, group.description) : null, rows);
}

function keysGroup(service) {
  const rows = el("div", { class: "rows" });
  for (const k of service.keys) {
    const input = el("input", { type: k.secret ? "password" : "text", value: k.value,
                                placeholder: k.set ? "zapisany - wklej nowy, żeby zmienić" : "brak" });
    const status = el("div", { class: "hint" }, k.set ? "zapisany" : "nie ustawiony");
    const save = button("Zapisz", async () => {
      try {
        const r = await api("/api/key", { name: k.name, value: input.value });
        status.textContent = r.set ? "zapisany" : "nie ustawiony";
        if (k.secret) { input.value = ""; input.placeholder = r.set ? "zapisany - wklej nowy, żeby zmienić" : "brak"; }
        toast(r.warning ? `Zapisano, ale ${r.warning}` : r.set ? `Zapisano: ${k.title}` : `Usunięto: ${k.title}`);
      } catch (e) { toast(e.message); }
    });
    rows.append(el("div", { class: "row" }, el("div", { class: "label" }, k.title, status), input, save));
  }
  for (const link of service.links) {
    rows.append(el("a", { class: "row link", href: link.url, target: "_blank", rel: "noopener" },
      el("div", { class: "label" }, link.title, el("div", { class: "hint" }, link.hint)), "↗"));
  }
  return el("div", { class: "group" }, el("h3", {}, service.title), el("div", { class: "desc" }, service.description), rows);
}

// --- start ----------------------------------------------------------------------------------------

function init() {
  $("#menu-button").innerHTML = ICONS.menu;
  $("#menu-button").addEventListener("click", mainMenu);
  $("#filter").addEventListener("change", (e) => {
    state.filter = e.target.value === "*" ? null : e.target.value;
    renderList();
  });
  for (const b of document.querySelectorAll("#session-tabs button")) {
    b.addEventListener("click", async () => {
      if (state.tab === "mowcy" && b.dataset.tab !== "mowcy" && !(await autosaveSpeakers())) return;
      state.tab = b.dataset.tab;
      renderSession();
    });
  }
  $("#search-button").innerHTML = ICONS.search;
  $("#search-button").addEventListener("click", searchDialog);
  $("#add-notes").innerHTML = ICONS.plus;
  $("#add-notes").addEventListener("click", () => notesDialog());
  initPlayer();
  for (const b of document.querySelectorAll("#main-switch button")) b.addEventListener("click", () => showMain(b.dataset.main));
  $("#process-all").addEventListener("click", () =>
    startTask("Pełny przebieg", ["run", "--no-interactive", ...providerArgs()]));
  $("#process-all").dataset.task = "1";
  $("#add-campaign").addEventListener("click", addCampaignMenu);
  window.addEventListener("beforeunload", (e) => {   // przeglądarka; okna GTK i pywebview wołają confirmClose
    if (state.running || speakersEdited() || unsavedTexts()) e.preventDefault();
  });
  $("#task-cancel").addEventListener("click", () => api("/api/task/cancel", {}));
  $("#task-log").addEventListener("click", showLog);
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "1") showMain("sesje");
    if (e.ctrlKey && (e.key === "2" || e.key === "k")) { e.preventDefault(); showMain("kampanie"); }
    if (e.ctrlKey && e.key === "f") { e.preventDefault(); searchDialog(); }
    if (e.ctrlKey && e.key === "n") { e.preventDefault(); notesDialog(); }
  });
  // Sygnał życia: w trybie przeglądarki serwer kończy pracę, gdy okno zostanie zamknięte
  setInterval(() => api("/api/task?since=" + state.seq).then((t) => { if (t.running && !state.running) pollTask(); })
    .catch(() => {}), 5000);
  if (HASH.get("tab")) state.tab = HASH.get("tab");
  if (HASH.get("tryb")) state.mode = HASH.get("tryb");
  // #okno=… otwiera okno dialogowe od razu (zrzuty ekranu i test okna bez klikania)
  const dialogs = { szukaj: searchDialog, notatki: () => notesDialog(), ustawienia: showSettings, nowosci: showChangelog,
                    discord: discordDialog, popraw: reviseDialog, usun: () => confirmDelete("kronika") };
  if (HASH.get("kampania")) {
    camp.key = HASH.get("kampania");
    camp.tab = HASH.get("ktab") || camp.tab;
  }
  refresh().then(() => camp.key ? showMain("kampanie") : null)
    .then(() => HASH.get("haslo") ? openEntry(HASH.get("haslo")) : null)
    .then(() => HASH.get("s") ? loadSession(HASH.get("s"), false) : null)
    .then(() => { const open = dialogs[HASH.get("okno")]; if (open) return open(); })
    .then(pollTask).catch((e) => {
    $("#view").replaceChildren(el("div", { class: "empty" }, el("h2", {}, "Nie można połączyć się z programem"),
                                  el("div", {}, e.message)));
  });
}

document.addEventListener("DOMContentLoaded", init);
