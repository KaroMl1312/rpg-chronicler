// RPG Chronicles - synchronizacja danych kampanii z Google Drive: postęp w tle, wynik, konflikty.

const syncView = { seq: null, timer: null, data: null };

async function startSync() {
  try { syncView.data = await api("/api/sync", {}); } catch (e) { return toast(e.message); }
  if (!syncView.data.running && syncView.data.error) toast(`Synchronizacja kampanii: ${syncView.data.error}`);
  watchSync();
}

// Pyta o stan co 2 s, dopóki synchronizacja trwa; po zakończeniu pokazuje wynik i odświeża widok
function watchSync() {
  clearTimeout(syncView.timer);
  const tick = async () => {
    const s = await api("/api/sync").catch(() => null);
    if (!s) return;
    const first = syncView.seq === null;
    const finished = !first && s.seq !== syncView.seq;
    syncView.data = s;
    syncView.seq = s.seq;
    renderSyncBar();
    if (finished && !s.running) {
      if (s.error) toast(`Synchronizacja kampanii nie udała się: ${s.error}`);
      else if (s.result && s.result.changed) {
        toast(`Kampanie zsynchronizowane: ${s.result.summary}`);
        await refresh();
      }
    }
    if (s.running) syncView.timer = setTimeout(tick, 2000);
  };
  tick();
}

function renderSyncBar() {
  const s = syncView.data, bar = $("#sync-bar");
  const pending = s ? s.pending : [];
  bar.hidden = !(s && (s.running || pending.length));
  if (bar.hidden) return;
  if (pending.length) {
    bar.className = "sync-bar conflict";
    bar.replaceChildren(el("span", { class: "grow" },
      `Konflikty synchronizacji kampanii (${pending.length}): ten sam plik zmieniono na dwóch komputerach.`),
      button("Rozstrzygnij", () => conflictsDialog()));
  } else {
    bar.className = "sync-bar";
    bar.replaceChildren(el("span", { class: "grow hint" }, "Synchronizacja kampanii z Google Drive…"));
  }
}

async function conflictsDialog(selected) {
  const s = await api("/api/sync").catch(() => null);
  if (!s || !s.pending.length) { toast("Brak konfliktów."); return renderSyncBar(); }
  const current = s.pending.includes(selected) ? selected : s.pending[0];
  let detail;
  try { detail = await api(`/api/sync/conflict?path=${encodeURIComponent(current)}`); } catch (e) { return toast(e.message); }

  const version = (title, v, hint) => {
    const body = !v ? el("div", { class: "hint" }, "brak pliku")
      : v.text !== undefined ? el("textarea", { class: "mono conflict-text", readonly: true }, v.text)
      : v.image ? el("img", { class: "conflict-image", src: v.image, alt: title })
      : el("div", { class: "hint" }, "plik bez podglądu");
    return el("div", { class: "conflict-side" }, el("h4", {}, title),
      el("div", { class: "hint" }, v ? `${hint} · zmieniony ${v.modified.replace("T", " ")} · ${Math.ceil(v.size / 1024)} KB` : hint),
      body);
  };
  const choose = async (keep, label) => {
    try {
      const r = await api("/api/sync/resolve", { path: current, keep });
      syncView.data = r;
      toast(r.extra ? `${current}: zachowano obie wersje (z Drive jako ${r.extra})` : `${current}: ${label}`);
      dialog.close();
      renderSyncBar();
      await refresh();
      if (r.pending.length) conflictsDialog();
    } catch (e) { toast(e.message); }
  };
  const list = s.pending.length > 1 ? el("div", { class: "conflict-list" }, s.pending.map((p) =>
    el("button", { class: `chip${p === current ? " active" : ""}`, onclick: () => { dialog.close(); conflictsDialog(p); } }, p))) : null;
  const dialog = openDialog(`Konflikt: ${current}`, [
    list,
    el("p", { class: "hint" }, "Plik zmieniono na tym komputerze i na innym od ostatniej synchronizacji. Obie wersje są "
       + "bezpieczne, dopóki nie wybierzesz. „Zachowaj obie” zapisze wersję z Drive obok, jako osobny plik."
       + (current.endsWith("kampanie.toml") ? " Przy kampanie.toml program czyta tylko plik o tej nazwie - "
          + "po „Zachowaj obie” przenieś potrzebne zmiany ręcznie." : "")),
    el("div", { class: "conflict-sides" },
      version("Na tym komputerze", detail.local, "ta wersja jest teraz używana"),
      version("Na Google Drive", detail.remote, "z innego komputera")),
  ], { cls: "conflicts", footer: [
    button("Zachowaj obie", () => choose("both", "zachowano obie wersje")),
    button("Weź z Drive", () => choose("remote", "użyto wersji z Drive")),
    button("Zostaw moją", () => choose("local", "zostawiono wersję z tego komputera"), "btn suggested"),
  ] });
}
