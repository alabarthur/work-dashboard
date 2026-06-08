// In-dashboard prioritization rules editor. Edits a working copy of rules.json
// and hands the result back to app.js, which PUTs it and re-ranks.

let rules = null;
let onSave = null;

function setPath(obj, path, val) {
  const keys = path.split(".");
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) o = o[keys[i]] = o[keys[i]] ?? {};
  o[keys[keys.length - 1]] = val;
}
function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

function slider(label, path, min, max, step) {
  const val = getPath(rules, path) ?? 0;
  return `
    <div class="slider">
      <div class="slider-head"><span>${label}</span><span data-out="${path}">${val}</span></div>
      <input type="range" data-path="${path}" data-type="num" min="${min}" max="${max}" step="${step}" value="${val}" />
    </div>`;
}

function chips(kind, arr, keyName) {
  const rows = arr
    .map(
      (e, i) => `<span class="chip">${escapeHtml(String(e[keyName]))} <b>+${e.boost}</b>
        <button data-del="${kind}" data-i="${i}">×</button></span>`
    )
    .join("");
  return `
    <div class="chip-row" data-chips="${kind}">${rows || '<span class="item-why">none</span>'}</div>
    <div class="chip-add">
      <input class="match" type="text" placeholder="${keyName}…" data-add-match="${kind}" />
      <input class="boost" type="number" placeholder="boost" data-add-boost="${kind}" />
      <button class="btn btn--ghost" data-add="${kind}">Add</button>
    </div>`;
}

export function open(currentRules, saveFn) {
  rules = JSON.parse(JSON.stringify(currentRules));
  onSave = saveFn;
  build();
  document.getElementById("rules-overlay").hidden = false;
  document.getElementById("rules-panel").classList.add("is-open");
  document.getElementById("rules-panel").setAttribute("aria-hidden", "false");
}

export function close() {
  document.getElementById("rules-overlay").hidden = true;
  document.getElementById("rules-panel").classList.remove("is-open");
  document.getElementById("rules-panel").setAttribute("aria-hidden", "true");
  setMsg("");
}

function build() {
  const body = document.getElementById("rules-body");
  body.innerHTML = `
    <div class="rules-group">
      <h3>Workday</h3>
      <div class="field-row">
        <div><label class="field-label">Start</label><input type="time" data-path="workday.start" value="${getPath(rules, "workday.start")}"/></div>
        <div><label class="field-label">End</label><input type="time" data-path="workday.end" value="${getPath(rules, "workday.end")}"/></div>
      </div>
      <label class="field-label" style="margin-top:12px">Timezone</label>
      <input type="text" data-path="workday.timezone" value="${escapeHtml(getPath(rules, "workday.timezone"))}"/>
      ${slider("Refresh interval (min)", "refresh.interval_minutes", 1, 60, 1)}
    </div>

    <div class="rules-group">
      <h3>Source weights</h3>
      ${slider("Teams", "source_weights.teams", 0, 2, 0.1)}
      ${slider("Email", "source_weights.outlook_email", 0, 2, 0.1)}
      ${slider("Calendar", "source_weights.calendar", 0, 2, 0.1)}
      ${slider("Notion", "source_weights.notion", 0, 2, 0.1)}
      ${slider("Base score", "base_score", 0, 60, 1)}
    </div>

    <div class="rules-group">
      <h3>VIP people</h3>
      ${chips("vip", rules.vip_people, "match")}
    </div>
    <div class="rules-group">
      <h3>Keywords</h3>
      ${chips("kw", rules.keywords, "match")}
    </div>
    <div class="rules-group">
      <h3>Notion tag boosts</h3>
      ${chips("tag", rules.notion_tag_boosts, "tag")}
      ${slider("Dependency boost", "notion_dependency_boost", 0, 40, 1)}
    </div>

    <div class="rules-group">
      <h3>Due-date urgency</h3>
      ${slider("Overdue", "due_date_urgency.overdue", 0, 80, 1)}
      ${slider("Due today", "due_date_urgency.due_today", 0, 60, 1)}
      ${slider("Due tomorrow", "due_date_urgency.due_tomorrow", 0, 40, 1)}
      ${slider("Decay window (days)", "due_date_urgency.decay_days", 1, 21, 1)}
    </div>

    <div class="rules-group">
      <h3>Meetings</h3>
      ${slider("Lead time (min)", "meeting_imminence.lead_minutes", 0, 60, 1)}
      ${slider("Max boost", "meeting_imminence.max_boost", 0, 100, 1)}
    </div>

    <div class="rules-group">
      <h3>Tiers & display</h3>
      ${slider("“Now” threshold", "tiers.now", 0, 150, 1)}
      ${slider("“Soon” threshold", "tiers.soon", 0, 120, 1)}
      ${slider("Do-now list size", "do_now_limit", 1, 30, 1)}
      ${slider("Manual ▲▼ step", "manual_step", 1, 50, 1)}
    </div>`;

  body.oninput = (e) => {
    const out = body.querySelector(`[data-out="${e.target.dataset.path}"]`);
    if (out) out.textContent = e.target.value;
  };
  body.onclick = onBodyClick;
}

function onBodyClick(e) {
  const { add, del, i } = e.target.dataset;
  if (add) {
    const matchEl = document.querySelector(`[data-add-match="${add}"]`);
    const boostEl = document.querySelector(`[data-add-boost="${add}"]`);
    const m = matchEl.value.trim();
    const b = parseFloat(boostEl.value);
    if (!m || Number.isNaN(b)) return;
    const { arr, key } = arrFor(add);
    arr.push({ [key]: m, boost: b });
    matchEl.value = boostEl.value = "";
    build();
  } else if (del) {
    const { arr } = arrFor(del);
    arr.splice(Number(i), 1);
    build();
  }
}

function arrFor(kind) {
  if (kind === "vip") return { arr: rules.vip_people, key: "match" };
  if (kind === "kw") return { arr: rules.keywords, key: "match" };
  return { arr: rules.notion_tag_boosts, key: "tag" };
}

function collect() {
  document.querySelectorAll("#rules-body [data-path]").forEach((el) => {
    const val = el.dataset.type === "num" ? Number(el.value) : el.value;
    setPath(rules, el.dataset.path, val);
  });
  return rules;
}

export function bindControls() {
  document.getElementById("rules-save").onclick = async () => {
    setMsg("saving…");
    const ok = await onSave(collect());
    setMsg(ok ? "saved · re-ranked" : "save failed");
    if (ok) setTimeout(close, 700);
  };
}

function setMsg(t) {
  document.getElementById("rules-msg").textContent = t;
}
function escapeHtml(s) {
  return (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
