// RPG Chronicles - nowe okno, etap 4: panel nagrania (cisza, oś czasu, przycinanie, transkrypcja), uwagi jakości,
// statystyki, „Uzupełnij brakujące”. Korzysta z funkcji z app.js i sesja.js.
"use strict";

const LISTEN_SECONDS = 15;

// Wpisy w panelu przeżywają odświeżenie widoku (np. koniec innego zadania); nowa analiza zaczyna od propozycji
const rec = { id: null, start: "", end: "", gaps: 0, noise: null, plan: null, request: 0 };

async function renderRecording(d) {
  const again = $("#view").dataset.panel === d.name && $("#view .recording") !== null;
  if (!again) $("#view").replaceChildren(el("div", { class: "empty" }, "Wczytywanie…"));
  let r;
  try { r = await api(`/api/recording?name=${encodeURIComponent(d.name)}`); } catch (e) { return toast(e.message); }
  if (state.detail !== d || state.tab !== "transkrypcja" || state.main !== "sesje") return;
  const a = r.analysis;
  const id = [d.name, r.version, r.noise, a ? a.duration : ""].join("/");
  if (rec.id !== id) Object.assign(rec, { id, start: a ? a.start : "", end: a ? a.end : "", gaps: 0, noise: r.noise, plan: null });

  const page = el("div", { class: "page recording" });
  const rows = el("div", { class: "rows" }, el("div", { class: "row" },
    el("div", { class: "label" }, r.file, el("div", { class: "hint" }, r.details))));
  if (!r.header_ok) {
    rows.append(el("div", { class: "row" }, el("div", { class: "label warn-text" }, "Plik nie ma zapisanej długości",
      el("div", { class: "hint" }, "Tak zapisują niektóre dyktafony. Rozpoznawanie głosów nie odczyta takiego pliku - wykryj ciszę "
        + "i przytnij nagranie (nawet bez zmiany granic), żeby zapisać je od nowa."))));
  }
  page.append(groupBox("Nagranie", "", rows));
  if (r.error) page.append(el("div", { class: "notice warn" }, `Wykrywanie ciszy i przycinanie niedostępne: ${r.error}`));
  else page.append(silenceGroup(d, r));
  const trim = !r.error && a && (a.silences.length || !r.header_ok);
  if (trim) page.append(trimGroup(d, r));
  page.append(groupBox("Transkrypcja", "Transkrypcja z rozpoznawaniem głosów działa na procesorze i trwa zwykle 2/3 czasu nagrania albo "
    + "dłużej (zależnie od procesora). Jeśli chcesz przyciąć ciszę, zrób to wcześniej - po transkrypcji czasy przestałyby pasować do nagrania.",
    el("div", { class: "actions start" }, taskButton("Transkrybuj", `Transkrypcja ${d.name}`, ["transcribe", d.name],
      a && a.silences.length ? "btn" : "btn suggested"))));   // przy wykrytej ciszy główną akcją jest przycięcie
  const scroll = again ? $("#view").scrollTop : 0;
  $("#view").replaceChildren(page);
  $("#view").dataset.panel = d.name;
  $("#view").scrollTop = scroll;
  if (trim) updatePlan(d, r);
}

function silenceGroup(d, r) {
  const a = r.analysis;
  const noise = el("select", { onchange: (e) => { rec.noise = Number(e.target.value); } },
    r.sensitivity.map((s) => el("option", { value: s.value, selected: s.value === rec.noise }, s.label)));
  const detect = button(a ? "Wykryj ponownie" : "Wykryj ciszę", () => startTask(`Wykrywanie ciszy ${d.name}`,
    ["silence", d.name, "--force", `--noise=${noise.value}`]), a ? "btn flat" : "btn suggested", { "data-task": true, disabled: state.running });
  let description;
  if (!a) {
    description = "Sprawdź, czy nagranie ma długie fragmenty ciszy - np. dyktafon włączony długo przed sesją albo zostawiony po niej. "
      + "Analiza trwa kilkanaście sekund, a przycięcie przed transkrypcją może ją znacznie skrócić.";
  } else if (!a.silences.length) {
    description = `Nie znaleziono ciszy dłuższej niż ${a.min_silence} s - nie ma czego przycinać. Przy szumach w tle spróbuj innej czułości.`;
  } else {
    description = `Cisza łącznie: ${a.total} w ${a.silences.length} fragmentach (≥ ${a.min_silence} s).`;
  }
  const rows = el("div", { class: "rows" });
  if (a && (a.silences.length || !r.header_ok)) rows.append(timeline(a));
  rows.append(el("div", { class: "row" }, el("div", { class: "label" }, "Czułość", el("div", { class: "hint" }, "Co uznawać za ciszę")), noise));
  if (a && a.silences.length) {
    rows.append(el("details", {}, el("summary", {}, el("b", {}, "Wykryte fragmenty ciszy"),
      el("span", { class: "hint" }, " odsłuchaj, czy to na pewno cisza, a nie np. cicha rozmowa")),
      a.silences.map((s, i) => {
        const middle = s.start + (s.end - s.start) / 2;
        return el("div", { class: "row" }, playButton(d.name, middle, middle + LISTEN_SECONDS, `cisza-${d.name}-${i}`, `Odsłuchaj ${LISTEN_SECONDS} s ze środka`),
          el("div", { class: "label" }, s.label), el("span", { class: "hint" }, s.duration));
      })));
  }
  return groupBox("Cisza w nagraniu", description, rows, detect);
}

// Oś czasu: pasek mowy, szare ciszy, przyciemnione wycinane fragmenty, czerwone granice, podziałka
function timeline(a) {
  const place = (cls, from, to) => {
    const node = el("div", { class: cls });
    node.style.left = `${100 * from / a.duration}%`;
    if (to !== undefined) node.style.width = `${100 * (to - from) / a.duration}%`;
    return node;
  };
  const step = a.duration > 7200 ? 3600 : 900;
  const marks = [];
  for (let t = 0; t <= a.duration; t += step) {
    const mark = place("mark", t);
    mark.textContent = step === 3600 ? `${t / 3600} h` : `${Math.floor(t / 3600)}:${String(t % 3600 / 60).padStart(2, "0")}`;
    marks.push(mark);
  }
  const cuts = el("div", { class: "cuts" });
  cuts.place = place;
  cuts.duration = a.duration;
  return el("div", { class: "row block" }, el("div", { class: "timeline" }, el("div", { class: "track" },
    a.silences.map((s) => place("silence", s.start, s.end)), cuts), el("div", { class: "marks" }, marks)),
    el("div", { class: "hint" }, "niebieskie – zostaje · szare – cisza · przyciemnione – zostanie wycięte"));
}

function drawCuts(plan) {
  const cuts = $("#view .cuts");
  if (!cuts) return;
  const nodes = [];
  let previous = 0;
  for (const [start, end] of [...plan.segments, [cuts.duration, cuts.duration]]) {
    if (start > previous) nodes.push(cuts.place("cut", previous, start));
    previous = end;
  }
  cuts.replaceChildren(...nodes, cuts.place("edge", plan.start), cuts.place("edge", plan.end));
}

function trimGroup(d, r) {
  const timeRow = (label, field, span, tooltip) => {
    const input = el("input", { type: "text", class: "short", value: rec[field], id: `trim-${field}`,
      oninput: (e) => { rec[field] = e.target.value; updatePlan(d, r); } });
    const play = el("button", { class: "btn flat play", title: tooltip, html: ICONS.play });
    play.dataset.key = `granica-${d.name}-${field}`;
    play.addEventListener("click", () => { if (rec.plan) togglePlay(d.name, ...span(rec.plan), play.dataset.key); });
    return el("div", { class: "row" }, el("div", { class: "label" }, label, el("div", { class: "hint" }, "gg:mm:ss")), play, input);
  };
  const gaps = el("input", { type: "number", min: 0, max: 600, value: rec.gaps, oninput: (e) => {
    rec.gaps = Math.max(0, Number(e.target.value) || 0);
    updatePlan(d, r);
  } });
  const rows = el("div", { class: "rows" },
    timeRow("Początek", "start", (p) => [p.start, p.start + LISTEN_SECONDS], `Odsłuchaj ${LISTEN_SECONDS} s od początku`),
    timeRow("Koniec", "end", (p) => [Math.max(0, p.end - LISTEN_SECONDS), p.end], `Odsłuchaj ${LISTEN_SECONDS} s przed końcem`),
    el("div", { class: "row" }, el("div", { class: "label" }, "Wytnij przerwy w środku dłuższe niż (min)",
      el("div", { class: "hint", id: "trim-gaps" }, "0 = nie wycinaj")), gaps),
    el("div", { class: "row" }, el("div", { class: "label" }, "Po przycięciu", el("div", { class: "hint", id: "trim-plan" }))));
  const trim = button("Przytnij nagranie", () => confirmTrim(d), "btn suggested", { id: "trim-run", disabled: true });
  return groupBox("Przycięcie", "Zostaje fragment od początku do końca. Odsłuchaj granice, żeby nie uciąć rozmowy.",
    el("div", {}, rows, el("div", { class: "actions start" }, trim)));
}

let planTimer = null;
function updatePlan(d, r) {
  rec.plan = null;   // do czasu odpowiedzi nie wiadomo, co zostanie - przycięcie zablokowane
  updateTrimButton();
  clearTimeout(planTimer);
  const request = ++rec.request;
  planTimer = setTimeout(async () => {
    const params = new URLSearchParams({ name: d.name, start: rec.start, end: rec.end, gaps: rec.gaps });
    let plan;
    try { plan = await api(`/api/recording/plan?${params}`); } catch (e) { plan = { error: e.message }; }
    const text = $("#trim-plan");
    if (request !== rec.request || !text) return;
    text.textContent = plan.error || plan.text;
    text.classList.toggle("error-text", Boolean(plan.error));
    if (!plan.error) {
      rec.plan = plan;
      $("#trim-gaps").textContent = "0 = nie wycinaj" + (plan.longest ? ` · najdłuższa przerwa w środku: ${plan.longest}` : "");
      drawCuts(plan);
    }
    updateTrimButton();
  }, 150);
}

// „Przytnij” działa tylko bez zadania w toku i gdy plan coś zmienia (nie przez data-task, które włączałoby go zawsze)
function updateTrimButton() {
  const trim = $("#trim-run");
  if (trim) trim.disabled = state.running || !rec.plan || !rec.plan.changes;
}

async function confirmTrim(d) {
  const plan = rec.plan;
  if (!plan) return;
  const answer = await ask("Przyciąć nagranie?", `${plan.text}\n\nOryginał zostanie przeniesiony do folderu „${plan.backup}” obok nagrania. `
    + "Na Google Drive nic się nie zmienia, a synchronizacja nie nadpisze przyciętego pliku.", [["cancel", "Anuluj"], ["trim", "Przytnij", "suggested"]]);
  if (answer === "trim") startTask(`Przycinanie ${d.name}`, plan.args);
}

// --- uwagi jakości i statystyki (pasek nad transkrypcją) -------------------------------------------------------------

function transcriptToolbar(d, t) {
  const items = [];
  if (t.issues.length) {
    items.push(el("button", { class: "btn flat warn-text", title: `Uwagi do transkrypcji: ${t.issues.length}`, onclick: () => issuesDialog(d, t) },
      `⚠ Uwagi (${t.issues.length})`));
  } else if (t.undo_loops) {
    items.push(undoLoopsButton(d, "btn flat"));
  }
  items.push(el("span", { class: "info", title: t.info }, t.info));
  if (t.stats) items.push(button("Statystyki", () => statsDialog(d)));
  return items;
}

function undoLoopsButton(d, cls) {
  return taskButton("Przywróć sprzed usunięcia powtórzeń", `Przywracanie transkrypcji ${d.name}`, ["fix-loops", d.name, "--undo"], cls,
                    "Wróć do transkrypcji sprzed ostatniego usunięcia powtórzeń Whispera");
}

function issuesDialog(d, t) {
  const body = t.issues.map((i, n) => el("div", { class: "hit" },
    i.at !== null && d.audio ? playButton(d.name, i.at, i.at + LISTEN_SECONDS, `uwaga-${d.name}-${n}`, "Odsłuchaj to miejsce") : null,
    el("div", { class: "body" }, i.text)));
  const footer = [];
  if (t.undo_loops) footer.push(undoLoopsButton(d, "btn"));
  if (t.loops) {
    footer.push(taskButton("Usuń powtórzenia", `Usuwanie powtórzeń ${d.name}`, ["fix-loops", d.name], "btn suggested",
                           "Z każdego ciągu zostaje pierwsza wypowiedź; kopia do cofnięcia zostaje"));
  }
  const dialog = openDialog("Podejrzane miejsca w transkrypcji", body, { footer, onclose: stopPlayback });
  for (const b of dialog.querySelectorAll(".dlg-foot button")) b.addEventListener("click", () => dialog.close());
}

async function statsDialog(d) {
  const body = el("div");
  const show = async (campaign) => {
    let s;
    try { s = await api(`/api/stats?name=${encodeURIComponent(d.name)}&campaign=${campaign ? 1 : 0}`); } catch (e) { return toast(e.message); }
    const scope = el("div", { class: "switcher settings-tabs" },
      el("button", { class: campaign ? "" : "active", onclick: () => show(false) }, "Ta sesja"),
      s.campaign ? el("button", { class: campaign ? "active" : "", onclick: () => show(true) }, `Cała kampania${campaign ? ` (sesje: ${s.count})` : ""}`) : null);
    body.replaceChildren(scope, ...s.summary.map((line) => el("div", {}, line)),
      el("div", { class: "stats" }, s.speakers.map((x) => {
        const bar = el("div");
        bar.style.width = `${100 * x.share}%`;
        return el("div", { class: "stat", title: x.details }, el("span", { class: "one-line" }, x.name), el("div", { class: "progress" }, bar),
                  el("span", { class: "hint" }, `${Math.round(100 * x.share)}% · ${x.time}`));
      })));
  };
  openDialog(`Statystyki ${d.name}`, body);
  await show(false);
}

// --- uzupełnij brakujące -----------------------------------------------------------------------------------------------

async function backfillDialog() {
  let plan;
  try { plan = await api("/api/backfill"); } catch (e) { return toast(e.message); }
  if (!plan.count) return toast("Wszystko jest aktualne - nie ma czego uzupełniać");
  const label = state.data.providers.find((p) => p.key === state.data.provider)?.label || state.data.provider;
  const answer = await ask("Uzupełnić brakujące?", `${plan.summary}\n\nZapytań do AI: ok. ${plan.requests} (${label}). Gotowe pliki zostają, powstają `
    + "tylko brakujące i nieaktualne.", [["cancel", "Anuluj"], ["run", "Uzupełnij", "suggested"]]);
  if (answer === "run") startTask("Uzupełnianie brakujących", ["backfill", ...providerArgs()]);
}
