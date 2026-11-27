// RPG Chronicles - nagrywanie sesji: wybór mikrofonu z podglądem głośności, pasek nagrywania, dokończenie nagrania.

const capture = { status: null, timer: null, dialog: null, stopping: false };

function recordingActive() { return !!(capture.status && capture.status.recording); }

function formatClock(seconds) {
  seconds = Math.floor(seconds);
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatSize(bytes) {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(2).replace(".", ",")} GB` : `${Math.round(bytes / 1e6)} MB`;
}

// Wskaźnik głośności: -60 dB = pusty, 0 dB = pełny; czerwony przy przesterowaniu (powyżej -1 dB)
function levelMeter() {
  const fill = el("div");
  const node = el("div", { class: "level-meter", title: "Głośność mikrofonu" }, fill);
  node.update = (db) => {
    const fraction = Math.max(0, Math.min(1, (db + 60) / 60));
    fill.style.width = `${Math.round(fraction * 100)}%`;
    node.classList.toggle("clip", db > -1);
    node.classList.toggle("quiet", db <= -50);
  };
  node.update(-90);
  return node;
}

function addSessionMenu(e) {
  e.stopPropagation();
  popover(e.currentTarget, [
    { label: "Nagraj sesję…", onclick: recordDialog, disabled: recordingActive() },
    { label: "Dodaj sesję z notatek…", onclick: () => notesDialog() },
  ]);
}

async function recordDialog() {
  let form;
  try { form = await api("/api/rec/devices"); } catch (e) { return toast(e.message); }
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const campaign = el("input", { type: "text", list: "rec-campaigns", placeholder: "np. Warhammer",
                                 value: state.filter || (state.detail ? state.detail.campaign || "" : "") });
  const campaigns = el("datalist", { id: "rec-campaigns" }, form.campaigns.map((c) => el("option", { value: c })));
  const date = el("input", { type: "date", value: iso });
  const name = el("input", { type: "text", placeholder: "Kampania_RRMMDD" });
  const error = el("div", { class: "error-text" });
  const device = el("select", {}, form.devices.map((d) => el("option", { value: d.id, selected: d.id === form.device }, d.label)));
  const meter = levelMeter();
  const meterHint = el("div", { class: "hint" }, "Powiedz coś - pasek powinien się poruszać, ale nie dochodzić do czerwieni.");
  const upload = el("input", { type: "checkbox", checked: form.upload });
  let edited = false;
  name.addEventListener("input", () => { edited = true; error.textContent = ""; });
  const suggest = async () => {
    if (edited) return;
    const r = await api(`/api/rec/name?campaign=${encodeURIComponent(campaign.value)}&date=${date.value}`).catch(() => null);
    if (!r) return;
    name.value = r.name;
    error.textContent = r.error;
  };
  campaign.addEventListener("input", suggest);
  date.addEventListener("change", suggest);

  let previewing = false;
  const startPreview = async () => {
    try { await api("/api/rec/preview", { device: device.value }); previewing = true; }
    catch (e) { meterHint.textContent = e.message; return; }
    meterHint.textContent = "Powiedz coś - pasek powinien się poruszać, ale nie dochodzić do czerwieni.";
  };
  device.addEventListener("change", startPreview);
  const poll = setInterval(async () => {
    const s = await api("/api/rec/status").catch(() => null);
    if (!s) return;
    meter.update(s.level);
    if (s.error && !s.preview) meterHint.textContent = `Mikrofon nie działa: ${s.error}`;
  }, 200);

  const startButton = button("Zacznij nagrywanie", async () => {
    if (!name.value.trim()) { error.textContent = "Podaj nazwę sesji."; return; }
    try {
      capture.status = await api("/api/rec/start", { name: name.value.trim(), device: device.value, upload: upload.checked });
    } catch (e) { error.textContent = e.message; return; }
    previewing = false;
    dialog.close();
    toast(`Nagrywanie ${name.value.trim()} rozpoczęte`);
    watchRecording();
  }, "btn suggested record-start");
  const dialog = openDialog("Nagraj sesję", [
    el("div", { class: "field" }, el("label", {}, "Kampania"), campaign, campaigns),
    el("div", { class: "field" }, el("label", {}, "Data sesji"), date),
    el("div", { class: "field" }, el("label", {}, "Nazwa sesji"),
       el("div", { class: "hint" }, "Tak będzie się nazywać nagranie, np. Warhammer_261127."), name, error),
    el("div", { class: "field" }, el("label", {}, "Mikrofon"), device, meter, meterHint),
    el("label", { class: "check" }, upload, " Po zakończeniu wyślij nagranie na Google Drive"),
    el("div", { class: "hint" }, "Po zatrzymaniu nagranie przechodzi przez filtr z ustawień (domyślnie: wycięcie basów "
       + "poniżej 80 Hz i kompresor) i trafia jako FLAC do folderu nagrań. Surowe nagranie zostaje w podfolderze oryginaly. "
       + "Na czas nagrywania komputer nie zaśnie."),
  ], { footer: [button("Anuluj", () => dialog.close()), startButton], onclose: () => {
    clearInterval(poll);
    if (previewing) api("/api/rec/stop", {}).catch(() => {});
  } });
  capture.dialog = dialog;
  await suggest();
  if (form.devices.length) startPreview();
  else meterHint.textContent = "Nie znaleziono mikrofonu - podłącz go i otwórz to okno ponownie.";
}

// Pasek u góry okna: trwające nagrywanie, przerwane nagranie albo nagrania do dokończenia
function renderRecording() {
  const s = capture.status, bar = $("#rec-bar");
  if (!s) { bar.hidden = true; return; }
  if (s.recording) {
    if (!bar.meter) bar.meter = levelMeter();
    bar.hidden = false;
    bar.className = "rec-bar live";
    bar.meter.update(s.level);
    const quiet = s.level <= -50 && s.elapsed > 10;
    bar.replaceChildren(el("span", { class: "rec-dot" }), el("b", {}, `Nagrywanie ${s.name}`),
      el("span", { class: "rec-time" }, formatClock(s.elapsed)), bar.meter,
      el("span", { class: "hint" }, `${formatSize(s.size)} · wolne miejsce na ok. ${String(s.free_hours).replace(".", ",")} h`),
      ...(quiet ? [el("span", { class: "warn-text" }, "cisza - sprawdź mikrofon")] : []),
      el("span", { class: "grow" }), button("Zatrzymaj", stopRecording, "btn destructive"));
    return;
  }
  bar.meter = null;
  const pending = s.unfinished || [];
  if (!pending.length) { bar.hidden = true; return; }
  bar.hidden = false;
  bar.className = "rec-bar pending";
  const why = s.interrupted && s.error ? `Nagrywanie ${s.interrupted} przerwane: ${s.error}. ` : "";
  bar.replaceChildren(el("span", { class: "grow" }, `${why}Nagranie do dokończenia: ${pending.join(", ")}`),
    ...pending.map((n) => taskButtonFinish(n)));
}

function taskButtonFinish(name) {
  return button(`Dokończ ${name}`, () => finishRecording(name), "btn", { "data-task": true, disabled: state.running });
}

async function finishRecording(name) {
  let r;
  try { r = await api(`/api/rec/finish-args?name=${encodeURIComponent(name)}`); } catch (e) { return toast(e.message); }
  state.openAfterTask = name;
  await startTask(`Obróbka nagrania ${name}`, r.args);
}

async function stopRecording() {
  const s = capture.status;
  const answer = await ask("Zakończyć nagrywanie?", `Nagranie ${s.name} (${formatClock(s.elapsed)}) zostanie zatrzymane i przetworzone.`,
                           [["no", "Nagrywaj dalej"], ["stop", "Zakończ nagrywanie", "destructive"]]);
  if (answer !== "stop") return;
  let r;
  capture.stopping = true;
  try { r = await api("/api/rec/stop", {}); } catch (e) { capture.stopping = false; return toast(e.message); }
  capture.stopping = false;
  capture.status = r;
  renderRecording();
  if (!r.stopped) return;
  if (state.running) {
    toast(`Nagranie ${r.stopped} zapisane. Obróbkę uruchomisz przyciskiem „Dokończ”, gdy skończy się bieżące zadanie.`);
    return;
  }
  finishRecording(r.stopped);
}

async function updateRecording() {
  const s = await api("/api/rec/status").catch(() => null);
  if (!s) return;
  const was = capture.status && capture.status.recording ? capture.status.name : null;
  capture.status = s;
  renderRecording();
  if (was && !s.recording && !capture.stopping) {
    // ffmpeg zakończył się sam: odłączony mikrofon, błąd urządzenia, brak miejsca
    ask("Nagrywanie zostało przerwane", `Nagrywanie ${was} zatrzymało się samo${s.error ? `: ${s.error}` : ""}. `
        + "To, co zdążyło się nagrać, jest zapisane - przetworzysz to przyciskiem „Dokończ” na górze okna. "
        + "Sprawdź, czy mikrofon jest podłączony.", [["ok", "Rozumiem"]]);
  }
}

// Odświeżanie paska: co sekundę w czasie nagrywania, rzadziej poza nim
function watchRecording() {
  clearTimeout(capture.timer);
  const tick = async () => {
    await updateRecording();
    capture.timer = setTimeout(tick, recordingActive() ? 1000 : 10000);
  };
  tick();
}
