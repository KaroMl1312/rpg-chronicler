// RPG Chronicles - nowe okno, etap 2: odsłuch nagrania, mówcy, poprawka kroniki, Discord, notatki MG,
// usuwanie i wyszukiwarka. Korzysta z funkcji z app.js (api, el, button, openDialog, ask, popover, startTask…).
"use strict";

const QUOTE_BEFORE = 1.0, QUOTE_AFTER = 4.0;   // czasy Whispera bywają za wczesne - lepiej dłużej niż uciąć
const SEARCH_MARGIN = 1.0;

// --- odsłuch fragmentów nagrania ------------------------------------------------------------------

const player = { key: null, end: 0, buttons: new Set() };

function playButton(session, start, end, key, title = "Odsłuchaj") {
  const node = el("button", { class: "btn flat play", title, html: ICONS.play });
  node.dataset.key = key;
  node.addEventListener("click", (e) => { e.stopPropagation(); togglePlay(session, start, end, key); });
  if (player.key === key) { node.classList.add("playing"); node.innerHTML = ICONS.stop; }
  return node;
}

function updatePlayButtons() {
  for (const node of document.querySelectorAll(".play")) {
    const playing = node.dataset.key === player.key;
    node.classList.toggle("playing", playing);
    node.innerHTML = playing ? ICONS.stop : ICONS.play;
  }
}

function stopPlayback() {
  const audio = $("#player");
  audio.pause();
  player.key = null;
  updatePlayButtons();
}

function togglePlay(session, start, end, key) {
  const audio = $("#player");
  if (player.key === key) return stopPlayback();
  const src = `/api/audio?name=${encodeURIComponent(session)}&t=${encodeURIComponent(TOKEN)}`;
  player.key = key;
  if (!audio.src.endsWith(src)) { audio.src = src; audio.load(); }   // bez load() metadane by nie przyszły
  player.end = end;
  const begin = () => {
    if (player.key !== key) return;   // w międzyczasie kliknięto inny fragment albo stop
    audio.currentTime = Math.max(0, start);
    audio.play().catch((e) => { toast(`Nie można odtworzyć nagrania: ${e.message}`); stopPlayback(); });
  };
  if (audio.readyState >= 1) begin();
  else audio.addEventListener("loadedmetadata", begin, { once: true });
  updatePlayButtons();
}

function initPlayer() {
  const audio = $("#player");
  audio.addEventListener("timeupdate", () => { if (player.key && audio.currentTime >= player.end) stopPlayback(); });
  audio.addEventListener("ended", stopPlayback);
  audio.addEventListener("error", () => { if (player.key) { toast("Nie można odtworzyć nagrania"); stopPlayback(); } });
}

function quotePlayButton(d, q, index) {
  if (q.start === null || q.start === undefined || !d.audio) return null;
  return playButton(d.name, Math.max(0, q.start - QUOTE_BEFORE), (q.end ?? q.start + 10) + QUOTE_AFTER,
                    `cytat-${d.name}-${index}`, "Odsłuchaj ten cytat");
}

// --- mówcy --------------------------------------------------------------------------------------

const speakersState = { name: null, saved: {}, inputs: {}, prefilled: false };

function speakerEdits() {
  return Object.fromEntries(Object.entries(speakersState.inputs).map(([k, input]) => [k, input.value.trim()]));
}

async function saveSpeakers(notify = true) {
  const name = speakersState.name;
  const mapping = speakerEdits();
  if (!Object.values(mapping).some(Boolean)) { if (notify) toast("Wpisz imię przynajmniej jednego mówcy"); return false; }
  try {
    const r = await api("/api/speakers", { name, mapping });
    speakersState.saved = mapping;
    speakersState.prefilled = false;
    if (notify && !r.has_summary) {
      toast("Zapisano mówców", "Generuj kronikę", () => { state.tab = "kronika"; loadSession(name, false).then(() => summarize(false)); });
    } else {
      toast(notify ? "Zapisano mówców" : `Zapisano mówców sesji ${name}`);
    }
    return true;
  } catch (e) { toast(e.message); return false; }
}

// Niezapisane imiona zapisujemy przy zmianie sesji, zakładki i przed kroniką (jak w starym oknie)
// Zwraca false, gdy zapis się nie udał i użytkownik woli zostać (wpisy zostają w polach).
async function autosaveSpeakers() {
  if (!(await saveSpeakerEdits())) return false;
  forgetSpeakers();
  return true;
}

async function saveSpeakerEdits() {
  if (!speakersEdited() || !Object.values(speakerEdits()).some(Boolean)) return true;
  return (await saveSpeakers(false)) || confirmDiscard("Nie udało się zapisać imion mówców.");
}

function forgetSpeakers() {
  speakersState.name = null;
  speakersState.inputs = {};
}

// Zmiany użytkownika (imiona wpisane przez rozpoznawanie głosu się nie liczą - zapis dopiero po zatwierdzeniu)
function speakersEdited() {
  return Boolean(speakersState.name) && JSON.stringify(speakerEdits()) !== JSON.stringify(speakersState.saved);
}

async function renderSpeakers() {
  const d = state.detail;
  $("#toolbar").hidden = true;
  // Odświeżenie tej samej sesji (np. koniec zadania): pola zostają na ekranie, a wpisy przechodzą do nowych
  const again = speakersState.name === d.name && $("#view .save-bar") !== null;
  if (!again) $("#view").replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
  let s;
  try { s = await api(`/api/speakers?name=${encodeURIComponent(d.name)}`); } catch (e) { return toast(e.message); }
  if (state.detail !== d || state.tab !== "mowcy" || state.main !== "sesje") return;
  const keep = again && speakersEdited() ? speakerEdits() : null;
  const scroll = again ? $("#view").scrollTop : 0;
  if (s.state !== "ok") {
    $("#view").replaceChildren(el("div", { class: "empty" },
      el("h2", {}, s.state === "brak-transkrypcji" ? "Brak transkrypcji" : "Brak rozpoznanych mówców"),
      el("div", {}, s.state === "brak-transkrypcji" ? "Mówców można nazwać po transkrypcji nagrania."
                    : "Ta transkrypcja powstała bez rozpoznawania głosów, więc nie ma kogo nazywać.")));
    return;
  }
  speakersState.name = d.name;
  speakersState.inputs = {};
  const page = el("div", { class: "page" });

  // rozpoznawanie głosów
  const voiceHead = el("div", { class: "section-head" }, el("h3", {}, "Rozpoznawanie głosów"));
  if (s.to_compute.length) {
    voiceHead.append(taskButton("Policz odciski głosu", `Odciski głosu (${s.to_compute.length} sesji)`,
                                ["voices", "--no-suggest", ...s.to_compute], "btn suggested"));
  } else if (s.has_suggestions) {
    voiceHead.append(button("Wpisz rozpoznane", () => fillRecognized(s, true), "btn flat",
                            { title: "Wpisz pewne rozpoznania w puste pola" }));
  }
  const voiceInfo = el("div", { class: "notice" }, s.voice_info);
  page.append(voiceHead, voiceInfo);

  // sugestia AI
  page.append(el("div", { class: "section-head" }, el("h3", {}, "Sugestia AI"),
    taskButton(s.suggestion_html ? "Zapytaj ponownie" : "Zapytaj AI", `Sugestia mówców ${d.name}`,
               ["speakers", "--suggest-only", ...providerArgs(), d.name], "btn flat")));
  page.append(s.suggestion_html ? el("div", { class: "suggestion chronicle", html: s.suggestion_html })
    : el("div", { class: "notice" }, "AI przeczyta transkrypcję i opisze każdego mówcę: kto jest MG, jakie postacie "
                                     + "prowadzą gracze. Trwa to zwykle 1–3 minuty."));

  // mówcy
  page.append(el("div", { class: "section-head" }, el("h3", {}, "Mówcy")));
  const datalist = el("datalist", { id: "speaker-names" },
    s.names.map((n) => el("option", { value: n.name }, n.player ? `${n.name} (${n.player})` : n.name)));
  page.append(datalist);
  for (const row of s.rows) {
    let meta = `${row.count} wypowiedzi · ${row.minutes} mówienia`;
    const v = row.voice;
    if (v) {
      meta += v.confident ? ` · głos: ${v.name} (${Math.round(v.score * 100)}%)`
                          : ` · głos: może ${v.name} (${Math.round(v.score * 100)}%)`;
      if (v.alternatives.length) meta += ", albo " + v.alternatives.map((a) => `${a.name} (${Math.round(a.score * 100)}%)`).join(", ");
    }
    const input = el("input", { type: "text", value: row.name, list: "speaker-names",
                                placeholder: "Imię postaci lub rola (np. MG, Hans)",
                                onkeydown: (e) => { if (e.key === "Enter") saveSpeakers(); } });
    speakersState.inputs[row.label] = input;
    const entry = el("div", { class: "entry" }, input);
    if (v && !v.confident) entry.append(button(`Użyj: ${v.name}`, () => { input.value = v.name; }, "btn flat"));
    if (row.samples.length && s.audio) {
      const first = row.samples[0];
      entry.prepend(playButton(d.name, first.start, first.end, `mowca-${d.name}-${row.label}-0`,
                               "Odsłuchaj najdłuższą wypowiedź"));
    }
    const card = el("div", { class: "speaker-card" },
      el("div", { class: "head" }, el("b", {}, row.label), el("span", { class: "meta" }, meta)), entry);
    if (row.samples.length) {
      card.append(el("details", {}, el("summary", {}, "Próbki głosu - najdłuższe wypowiedzi"),
        row.samples.map((x, i) => el("div", { class: "sample" },
          s.audio ? playButton(d.name, x.start, x.end, `mowca-${d.name}-${row.label}-${i}`) : null,
          el("div", { class: "text" }, x.text, el("div", { class: "when" }, `${x.time} · ${x.seconds} s`))))));
    }
    page.append(card);
  }
  speakersState.saved = speakerEdits();
  speakersState.prefilled = false;
  if (keep) {
    for (const [label, value] of Object.entries(keep)) {
      if (speakersState.inputs[label]) speakersState.inputs[label].value = value;
    }
  } else if (!d.has_speakers) {
    const filled = fillRecognized(s, false);
    if (filled) {
      speakersState.saved = speakerEdits();
      speakersState.prefilled = true;
      voiceInfo.textContent = `Wpisano ${filled} rozpoznanych imion - sprawdź (odsłuchaj w razie wątpliwości) i zapisz.`;
    }
  }
  page.append(el("div", { class: "save-bar" }, button("Zapisz mówców", () => saveSpeakers(), "btn suggested")));
  $("#view").replaceChildren(page);
  $("#view").scrollTop = scroll;
}

function fillRecognized(s, notify) {
  let filled = 0;
  for (const [label, name] of Object.entries(s.prefill)) {
    const input = speakersState.inputs[label];
    if (input && !input.value.trim()) { input.value = name; filled++; }
  }
  if (notify) toast(filled ? `Wpisano ${filled} imion` : "Nie ma pustych pól z pewnym rozpoznaniem");
  return filled;
}

// --- poprawka kroniki ---------------------------------------------------------------------------

function reviseDialog() {
  const d = state.detail;
  const text = el("textarea", { placeholder: "Np. „Dopisz, że Fen dostał od kapłanki amulet” albo "
                                             + "„Popraw imię Eustachy na Eustachos”" });
  const run = () => {
    const instruction = text.value.trim();
    if (!instruction) return toast("Napisz, co poprawić");
    dialog.close();
    startTask(`Poprawka kroniki ${d.name}`, ["revise", d.name, ...providerArgs(), "--", instruction]);
  };
  const dialog = openDialog("Popraw kronikę", [
    el("div", { class: "field" }, el("div", { class: "hint" },
      "Napisz, co zmienić. AI poprawi tylko to, czego dotyczy polecenie, korzystając z listy wydarzeń albo "
      + "transkrypcji. Poprzednią wersję można przywrócić („⋯” → Cofnij poprawkę)."), text)],
    { footer: [button("Anuluj", () => dialog.close()), button("Popraw", run, "btn suggested", { "data-task": true, disabled: state.running })] });
  text.focus();
}

async function undoRevision() {
  const d = state.detail;
  const answer = await ask("Cofnąć ostatnią poprawkę?", "Kronika wróci do wersji sprzed ostatniej poprawki. Skrót "
                           + "kroniki trzeba będzie napisać ponownie (zakładka Kronika → Skrót).",
                           [["cancel", "Anuluj"], ["undo", "Cofnij poprawkę", "destructive"]]);
  if (answer === "undo") startTask(`Cofnięcie poprawki ${d.name}`, ["revise", d.name, "--undo"]);
}

async function toggleSent() {
  const d = state.detail;
  try {
    await api("/api/discord/sent", { name: d.name, sent: !d.discord });
    toast(d.discord ? "Usunięto znacznik wysyłki (wiadomość na Discordzie zostaje)" : "Oznaczono jako wysłaną");
    await refresh();
  } catch (e) { toast(e.message); }
}

// --- Discord ----------------------------------------------------------------------------------------

async function discordDialog() {
  const d = state.detail;
  let info;
  try { info = await api(`/api/discord?name=${encodeURIComponent(d.name)}`); } catch (e) { return toast(e.message); }
  const body = el("div");
  const rows = el("div", { class: "rows" });
  if (info.webhook) {
    rows.append(el("div", { class: "row" }, el("div", { class: "label" }, `Kanał kampanii ${info.campaign}`,
      el("div", { class: "hint" }, "webhook ustawiony")),
      button("Zmień", () => { dialog.close(); showCampaign(info.campaign, "ogolne"); }, "btn flat")));
  } else {
    const input = el("input", { type: "password", placeholder: "https://discord.com/api/webhooks/…" });
    rows.append(el("div", { class: "row" }, el("div", { class: "label" }, `Adres webhooka kanału ${info.campaign}`,
      el("div", { class: "hint" }, "Na Discordzie: ustawienia kanału → Integracje → Webhooki → Nowy webhook → Kopiuj "
                                   + "adres URL. Adres zostaje tylko na tym komputerze.")), input,
      button("Zapisz", async () => {
        try {
          await api("/api/discord/webhook", { campaign: info.campaign, url: input.value });
          dialog.close();
          toast("Zapisano webhook kampanii");
          discordDialog();
        } catch (e) { toast(e.message); }
      })));
  }
  body.append(el("div", { class: "group" }, el("h3", {}, "Kanał"), rows));

  const teaser = el("textarea", {}, info.teaser);
  teaser.value = info.teaser;
  body.append(el("div", { class: "group" },
    el("div", { class: "section-head" }, el("h3", {}, "Zapowiedź"),
       button("Napisz (AI)", () => {
         dialog.close();
         startTask(`Zapowiedź ${d.name}`, ["discord", d.name, "--przygotuj", "--nowa-zapowiedz", ...providerArgs()]);
       }, "btn flat", { "data-task": true, disabled: state.running, title: "AI napisze zapowiedź (i przygotuje PDF)" })),
    el("div", { class: "desc" }, "2–3 zdania nad załącznikiem. Możesz ją poprawić albo napisać własną; pusta - AI "
                                 + "napisze ją przy wysyłaniu."), teaser));

  let quotesBox = null;
  if (info.quotes.length) {
    quotesBox = el("input", { type: "checkbox", checked: true });
    body.append(el("div", { class: "group" }, el("h3", {}, "Cytaty sesji"), el("div", { class: "rows" },
      el("div", { class: "row" }, el("div", { class: "label" }, `Dołącz cytaty pod zapowiedzią (${info.quotes.length})`,
        info.quotes.map((q) => el("div", { class: "hint" }, q))), el("label", { class: "switch" }, quotesBox, el("span"))))));
  }
  body.append(el("div", { class: "group" }, el("h3", {}, "Załącznik"), el("div", { class: "rows" },
    el("div", { class: "row" }, el("div", { class: "label" }, info.pdf_name,
      el("div", { class: "hint" }, info.pdf_current ? "aktualny" : "zostanie utworzony przy wysyłaniu"))))));
  body.append(el("div", { class: "desc" }, info.sent
    ? `Tę kronikę wysłano już ${info.sent}. Ponowne wysłanie doda nową wiadomość na kanale.`
    : "Wiadomość: tytuł kroniki, zapowiedź i PDF z całą kroniką."));

  const send = async () => {
    try { await api("/api/discord/teaser", { name: d.name, text: teaser.value }); } catch (e) { return toast(e.message); }
    const args = ["discord", d.name, ...providerArgs()];
    if (info.resend) args.push("--force");
    if (quotesBox && !quotesBox.checked) args.push("--no-quotes");
    dialog.close();
    startTask(`Wysyłanie kroniki ${d.name} na Discord`, args);
  };
  const dialog = openDialog("Wyślij na Discord", body, { footer: [
    button("Anuluj", () => dialog.close()),
    button("Wyślij", send, "btn suggested", { "data-task": true, disabled: state.running || !info.webhook }),
  ] });
}

// --- notatki MG ---------------------------------------------------------------------------------

async function notesDialog(name = null) {
  let form;
  try {
    form = await api(`/api/notes?name=${encodeURIComponent(name || "")}&campaign=${encodeURIComponent(
      state.filter || (state.detail ? state.detail.campaign || "" : ""))}`);
  } catch (e) { return toast(e.message); }
  const editing = Boolean(name);
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const campaign = el("input", { type: "text", value: form.campaign, list: "notes-campaigns", placeholder: "np. Warhammer" });
  const date = el("input", { type: "date", value: iso });
  const nameView = el("div", { class: "hint" });
  const error = el("div", { class: "error-text" });
  const checks = el("div", { class: "checks" });
  const text = el("textarea", { placeholder: "Notatki z przebiegu sesji…" });
  text.value = form.text;
  text.style.minHeight = "240px";
  const generate = el("input", { type: "checkbox", checked: !(editing && form.has_summary) });
  let present = form.present;   // null = wszyscy z kampanii

  const renderChecks = (characters) => {
    const chosen = new Set(present ?? characters);
    const all = [...characters, ...(present || []).filter((n) => !characters.includes(n))];
    checks.replaceChildren(...all.map((n) => el("label", {}, el("input", { type: "checkbox", value: n, checked: chosen.has(n) }), n)));
    checksField.hidden = !all.length;
  };
  const checksField = el("div", { class: "field" }, el("label", {}, "Obecne postacie graczy"),
    el("div", { class: "hint" }, "Trafią do kroniki i dziennika postaci (zamiast rozpoznawania mówców)."), checks);

  let lastName = "";
  const update = async () => {
    if (editing) { renderChecks(form.characters); return; }
    const r = await api(`/api/notes/name?campaign=${encodeURIComponent(campaign.value)}&date=${date.value}`).catch(() => null);
    if (!r) return;
    lastName = r.name;
    nameView.textContent = r.name ? `Nazwa sesji: ${r.name}` : "";
    error.textContent = campaign.value.trim() ? r.error : "";
    renderChecks(r.characters);
  };
  const fileInput = el("input", { type: "file", accept: ".md,.txt,text/plain", hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const buffer = await file.arrayBuffer();
    let content;
    try { content = new TextDecoder("utf-8", { fatal: true }).decode(buffer); }
    catch { content = new TextDecoder("windows-1250").decode(buffer); }
    text.value = content.replace(/^<!--.*?-->\s*\n?/, "");
  } });

  const body = [
    editing ? el("div", { class: "notice" }, `Sesja ${name}`)
            : el("div", { class: "notice" }, "Sesja, która nie była nagrywana: kronika powstanie z notatek MG. "
                                             + "Nie będzie nagrania, mówców ani cytatów."),
    editing ? null : el("div", { class: "field" }, el("label", {}, "Kampania"), campaign,
                        el("datalist", { id: "notes-campaigns" }, form.campaigns.map((c) => el("option", { value: c })))),
    editing ? null : el("div", { class: "field" }, el("label", {}, "Data sesji"), date, nameView),
    checksField,
    el("div", { class: "field" }, el("div", { class: "section-head" }, el("h3", {}, "Notatki"),
       button("Wczytaj z pliku…", () => fileInput.click(), "btn flat")), fileInput,
       el("div", { class: "hint" }, "Najlepiej w punktach: kto, gdzie, co się stało, co zdobyto, co ustalono. AI "
                                    + "rozwinie je w kronikę, ale nie dopisze zdarzeń, których tu nie ma."), text),
    el("label", { class: "checks" }, generate, editing && form.has_summary ? "Napisz kronikę od nowa" : "Od razu napisz kronikę"),
    error,
  ];
  const save = async () => {
    const chosen = [...checks.querySelectorAll("input:checked")].map((c) => c.value);
    try {
      const r = await api("/api/notes", { name, campaign: campaign.value, date: date.value, text: text.value, present: chosen });
      dialog.close();
      state.tab = generate.checked ? "kronika" : "transkrypcja";
      await refresh();
      await loadSession(r.name, false);
      if (generate.checked) {
        const args = ["summarize", "--no-interactive", ...providerArgs()];
        if (editing && form.has_summary) args.push("--force");
        startTask(`Kronika ${r.name}`, [...args, r.name]);
      }
    } catch (e) { error.textContent = e.message; }
  };
  campaign.addEventListener("input", update);
  date.addEventListener("change", update);
  const dialog = openDialog(editing ? "Notatki sesji" : "Dodaj sesję z notatek", body, { footer: [
    button("Anuluj", () => dialog.close()), button(editing ? "Zapisz" : "Dodaj sesję", save, "btn suggested")] });
  update();
}

// --- menu sesji: notatki i usuwanie -------------------------------------------------------------------

async function sessionMenu(e) {
  e.stopPropagation();
  const anchor = e.currentTarget;
  const d = state.detail;
  let options = [];
  try { options = await api(`/api/delete/options?name=${encodeURIComponent(d.name)}`); } catch (err) { return toast(err.message); }
  popover(anchor, [
    d.from_notes ? { label: "Edytuj notatki…", onclick: () => notesDialog(d.name) } : null,
    d.from_notes ? "-" : null,
    ...options.map((o) => ({ label: o.label, disabled: !o.enabled || state.running, onclick: () => confirmDelete(o.scope) })),
  ].filter(Boolean));
}

async function confirmDelete(scope) {
  const d = state.detail;
  let plan;
  try { plan = await api(`/api/delete?name=${encodeURIComponent(d.name)}&scope=${scope}`); } catch (e) { return toast(e.message); }
  const remove = button(plan.button, () => {
    dialog.close();
    startTask(`Usuwanie: ${plan.label} (${d.name})`, ["delete", d.name, "--zakres", scope, "--yes"]);
  }, "btn destructive", { disabled: Boolean(plan.confirm) || state.running });
  const body = [el("h3", {}, plan.heading), el("div", {}, plan.body), el("div", { class: "files" }, plan.files)];
  if (plan.warnings.length) body.push(el("div", { class: "notice warn" }, plan.warnings.join("\n")));
  if (plan.confirm) {
    body.push(el("label", { class: "checks" }, el("input", { type: "checkbox", onchange: (e) => { remove.disabled = !e.target.checked; } }),
                 plan.confirm));
  }
  const dialog = openDialog(null, body, { cls: "alert", footer: [button("Anuluj", () => dialog.close()), remove] });
}

// --- wyszukiwarka ---------------------------------------------------------------------------------------

function searchDialog() {
  const query = el("input", { type: "text", placeholder: "Szukaj imienia, miejsca, przedmiotu…" });
  const campaign = el("select", {}, el("option", { value: "" }, "Wszystkie kampanie"));
  const chronicles = el("input", { type: "checkbox", checked: true });
  const transcripts = el("input", { type: "checkbox", checked: true });
  const status = el("div", { class: "hint" });
  const results = el("div");
  let timer = null, loadedCampaigns = false;

  const run = async () => {
    stopPlayback();
    const params = new URLSearchParams({ q: query.value, campaign: campaign.value,
      chronicles: chronicles.checked ? "1" : "0", transcripts: transcripts.checked ? "1" : "0" });
    let r;
    try { r = await api(`/api/search?${params}`); } catch (e) { return toast(e.message); }
    if (!loadedCampaigns) {
      campaign.append(...r.campaigns.map((c) => el("option", { value: c }, c)));
      loadedCampaigns = true;
    }
    status.textContent = r.summary;
    results.replaceChildren(...r.hits.map((h) => {
      const where = h.tab === "kronika" || h.notes
        ? [h.session, h.kind, h.heading].filter(Boolean).join(" · ")
        : [h.session, h.time, h.speaker].filter(Boolean).join(" · ");
      return el("div", { class: "hit" },
        h.audio ? playButton(h.session, Math.max(0, h.start - SEARCH_MARGIN), h.end + SEARCH_MARGIN,
                             `szukaj-${h.session}-${h.start}`, "Odsłuchaj ten fragment nagrania") : null,
        el("div", { class: "body" }, el("div", { class: "where" }, where), el("div", { html: h.html })),
        button("Otwórz", () => {
          dialog.close();
          state.tab = h.tab;
          if (h.tab === "kronika") state.mode = "kronika";
          showMain("sesje").then((ok) => ok && loadSession(h.session, false));
        }, "btn flat", { title: h.tab === "kronika" ? "Otwórz kronikę" : "Otwórz transkrypcję" }));
    }));
  };
  query.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 300); });
  query.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); run(); } });
  for (const node of [campaign, chronicles, transcripts]) node.addEventListener("change", run);
  const dialog = openDialog("Szukaj w sesjach", [
    el("div", { class: "search-bar" }, query, campaign,
       el("label", { class: "checks" }, chronicles, "kroniki"), el("label", { class: "checks" }, transcripts, "transkrypcje")),
    status, results], { onclose: stopPlayback, cls: "tall" });
  query.focus();
  run();
}
