/* Strength Intelligence — dashboard renderer.
   Deliberately dependency-free: no build step, no framework, no CDN. */

const SUGGESTIONS = [
  "Is my deficit hurting my strength?",
  "How is my bench progressing?",
  "How was my fueling before my best workouts?",
  "Should I change my calories?",
  "Am I losing weight too quickly?",
];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const num = (v, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(digits);

const signed = (v, digits = 1) =>
  v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(digits);

/* A lift is "flat" when its 30-day move sits inside its own measured noise floor. */
function trendClass(pct, noise) {
  if (pct === null || pct === undefined) return "trend-flat";
  const threshold = Math.max(1.5, noise ?? 0);
  if (pct > threshold) return "trend-up";
  if (pct < -threshold) return "trend-down";
  return "trend-flat";
}

const ARROW = { "trend-up": "↑", "trend-down": "↓", "trend-flat": "→" };

const STATUS_PILL = {
  progressing: ["pill-up", "Progressing"],
  maintaining: ["pill-flat", "Maintaining"],
  regressing: ["pill-down", "Regressing"],
  insufficient_data: ["pill-flat", "Insufficient data"],
};

function sparkline(history) {
  if (!history || history.length < 2) return "";
  const vals = history.map((h) => h.e1rm);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const w = 200;
  const h = 34;
  const pad = 3;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts.join(" ")}" fill="none" stroke="currentColor"
      stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>
  </svg>`;
}

function weightChart(history, target) {
  if (!history || history.length < 2) return "";
  const vals = history.map((h) => h.body_weight);
  const lo = Math.min(...vals, target ?? Infinity);
  const hi = Math.max(...vals, target ?? -Infinity);
  const span = hi - lo || 1;
  const w = 600;
  const h = 108;
  const pad = 8;
  const y = (v) => h - pad - ((v - lo) / span) * (h - pad * 2);
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * w).toFixed(1)},${y(v).toFixed(1)}`);
  const targetLine =
    target === null || target === undefined
      ? ""
      : `<line x1="0" y1="${y(target).toFixed(1)}" x2="${w}" y2="${y(target).toFixed(1)}"
           stroke="currentColor" stroke-width="1" stroke-dasharray="3 3" opacity="0.3"/>
         <text x="4" y="${(y(target) - 5).toFixed(1)}" font-size="9" fill="currentColor"
           opacity="0.5">target ${num(target, 0)} lb</text>`;
  return `<svg class="weight-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    ${targetLine}
    <polyline points="${pts.join(" ")}" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linejoin="round" opacity="0.75"/>
  </svg>`;
}

function goalStrip(goal, weight) {
  const cells = [];
  cells.push(`<div class="goal-cell">
    <div class="label">Goal</div>
    <div class="value goal-type">${esc(goal.goal_type)}</div>
    <div class="sub">${num(goal.target_rate_of_change, 2)} lb/week target</div>
  </div>`);
  cells.push(`<div class="goal-cell">
    <div class="label">Body weight</div>
    <div class="value">${num(goal.starting_weight, 0)} → ${num(goal.target_weight, 0)} lb</div>
    <div class="sub">now ${num(weight.current_weight_7d_avg)} lb</div>
  </div>`);
  cells.push(`<div class="goal-cell">
    <div class="label">Calories</div>
    <div class="value">${esc(goal.calorie_target ?? "—")}</div>
    <div class="sub">kcal/day target</div>
  </div>`);
  cells.push(`<div class="goal-cell">
    <div class="label">Protein</div>
    <div class="value">${esc(goal.protein_target ?? "—")} g</div>
    <div class="sub">per day target</div>
  </div>`);
  cells.push(`<div class="goal-cell">
    <div class="label">Carbs / Fat</div>
    <div class="value">${esc(goal.carb_target ?? "—")} / ${esc(goal.fat_target ?? "—")} g</div>
    <div class="sub">per day target</div>
  </div>`);
  return `<div class="goal-strip">${cells.join("")}</div>`;
}

function liftCard(l) {
  const cls = trendClass(l.e1rm_change_30d_pct, l.session_variability_pct);
  const [pillCls, pillText] = STATUS_PILL[l.status] || ["pill-flat", l.status];
  const recent = l.recent_exposures || {};

  let note = "";
  if (recent.stalled && l.status === "progressing") {
    note = `Flat across last ${recent.exposures_in_window} exposures`;
  } else if (recent.persistent_decline) {
    note = `Declining across last ${recent.exposures_in_window} exposures`;
  } else if (recent.single_poor_session) {
    note = "One session below trend";
  } else if (recent.sufficient_recent_data === false) {
    note = `${recent.exposures_in_window} recent exposure(s)`;
  }

  return `<article class="lift-card ${cls}">
    <div class="lift-name">${esc(l.exercise)}</div>
    <span class="pill ${pillCls}">${esc(pillText)}</span>
    <div class="lift-delta">
      <span class="arrow">${ARROW[cls]}</span>
      <span class="figure">${signed(l.e1rm_change_30d_pct)}%</span>
    </div>
    <div class="metric-label">30-day estimated 1RM trend</div>
    ${sparkline(l.history)}
    <div class="lift-foot">
      <div class="working">${esc(l.current_working_weight ?? "—")} · e1RM ${num(l.current_e1rm)} lb</div>
      ${note ? `<div>${esc(note)}</div>` : ""}
    </div>
  </article>`;
}

function intelligencePanel(intel) {
  const action = intel.next_action || {};
  const conf = (intel.confidence || "low").toLowerCase();

  const section = (label, inner) =>
    `<div class="block"><div class="block-label">${label}</div>${inner}</div>`;

  const list = (items, extraCls = "") =>
    `<ul class="evidence-list ${extraCls}">${items
      .map((i) => `<li>${esc(i)}</li>`)
      .join("")}</ul>`;

  let html = `<div class="intel-lead">
    <p class="observation">${esc(intel.observation || intel.answer)}</p>
  </div><div class="intel-body">`;

  if (intel.evidence?.length) html += section("Evidence", list(intel.evidence));
  if (intel.interpretation)
    html += section("Interpretation", `<p>${esc(intel.interpretation)}</p>`);
  if (intel.alternative_explanations?.length)
    html += section("Alternative explanations", list(intel.alternative_explanations));
  if (intel.ruled_out?.length)
    html += section("Stable inputs (less likely to explain this)",
      list(intel.ruled_out, "ruled-out"));

  if (action.action) {
    const meta = [];
    if (action.hold_constant?.length)
      meta.push(`<span><strong>Hold constant:</strong> ${esc(action.hold_constant.join(", "))}</span>`);
    if (intel.reassess) meta.push(`<span><strong>Reassess:</strong> ${esc(intel.reassess)}</span>`);
    html += section("Recommended action", `<div class="action-box">
      <div class="action-title">${esc(action.action)}</div>
      <div class="action-detail">${esc(action.detail || "")}</div>
      ${action.rationale ? `<div class="action-detail">${esc(action.rationale)}</div>` : ""}
      ${meta.length ? `<div class="action-meta">${meta.join("")}</div>` : ""}
    </div>`);
  }

  html += section("Confidence", `<div class="confidence-row">
    <span class="conf-badge conf-${esc(conf)}">${esc(conf)}</span>
    <span class="conf-why">${esc(intel.confidence_reason || "")}</span>
  </div>`);

  return `<div class="intel">${html}</div></div>`;
}

function routeTrace(r) {
  const routing = r.routing || {};
  const agents = (r.agents_consulted || []).map((a) => a + "_agent");
  return `<div class="route-trace">
    <span class="k">intent</span> ${esc(routing.intent || "—")} &nbsp;
    <span class="k">agents</span> ${esc(agents.join(" + ") || "—")} &nbsp;
    <span class="k">focus</span> ${esc((routing.focus_lifts || []).join(", ") || "all lifts")} &nbsp;
    <span class="k">path</span> ${esc(r.path || "—")}<br>
    <span class="k">routing</span> ${esc(routing.rationale || "")}
  </div>`;
}

function renderAnswer(question, r) {
  document.getElementById("answer").innerHTML = `<div class="answer">
    <p class="answer-question">Asked: <span>${esc(question)}</span></p>
    ${routeTrace(r)}
    <p class="answer-lead">${esc(r.answer)}</p>
    ${intelligencePanel(r)}
  </div>`;
}

function weightPanel(w) {
  return `<div class="weight-panel">
    <div class="weight-stats">
      <div><div class="label">Current (7-day avg)</div><div class="value">${num(w.current_weight_7d_avg)} lb</div></div>
      <div><div class="label">30-day change</div><div class="value">${signed(w.change_last_30d)} lb</div></div>
      <div><div class="label">Target</div><div class="value">${num(w.target_weight, 0)} lb</div></div>
      <div><div class="label">Observed rate</div><div class="value">${num(w.observed_rate_lb_per_week_30d, 2)}</div></div>
      <div><div class="label">Desired rate</div><div class="value">${num(w.target_rate_lb_per_week, 2)}</div></div>
    </div>
    ${weightChart(w.history, w.target_weight)}
    <p class="rate-note">
      <span class="verdict ${esc(w.rate_verdict)}">${esc((w.rate_verdict || "").replace(/_/g, " "))}</span>
      — ${esc(w.rate_note || "")}
      ${w.estimated_weeks_to_target ? ` At the observed rate, roughly ${num(w.estimated_weeks_to_target)} weeks to target.` : ""}
    </p>
  </div>`;
}

function render(d) {
  const meta = document.getElementById("masthead-meta");
  meta.innerHTML = `Data through ${esc(d.as_of)}<br>
    ${esc(d.data_coverage.workout_rows)} workout rows ·
    ${esc(d.data_coverage.context_days)} days context<br>
    <span class="path-badge">${d.reasoning_path === "llm" ? "model interpretation" : "deterministic interpretation"}</span>`;

  const main = document.getElementById("main");
  main.className = "";
  main.innerHTML = `
    <section>
      <div class="section-head"><h2>Current Goal</h2></div>
      ${goalStrip(d.goal, d.weight)}
    </section>

    <section>
      <div class="section-head">
        <h2>Strength Overview</h2>
        <div class="section-note">${num(d.strength.sessions_per_week_last_30d)} sessions/week ·
          ${esc(d.strength.training_days_last_30d)} training days in 30 days</div>
      </div>
      <div class="lift-grid">${d.strength.lifts.map(liftCard).join("")}</div>
    </section>

    <section>
      <div class="section-head"><h2>Body Weight</h2></div>
      ${weightPanel(d.weight)}
    </section>

    <section>
      <div class="section-head">
        <h2>Current Intelligence</h2>
        <div class="section-note">Synthesised from ${esc((d.intelligence.agents_consulted || []).join(" + "))}</div>
      </div>
      ${intelligencePanel(d.intelligence)}
    </section>

    <section>
      <div class="section-head"><h2>Ask Strength Intelligence</h2></div>
      <div class="ask-panel">
        <form class="ask-form" id="ask-form">
          <input id="ask-input" type="text" autocomplete="off"
            placeholder="Why has my bench stalled?">
          <button type="submit" id="ask-btn">Ask</button>
        </form>
        <div class="suggestions" id="suggestions">
          ${SUGGESTIONS.map((s) => `<button type="button" data-q="${esc(s)}">${esc(s)}</button>`).join("")}
        </div>
        <div id="answer"></div>
      </div>
    </section>
  `;

  wireAsk();
}

async function submitQuestion(question) {
  const input = document.getElementById("ask-input");
  const btn = document.getElementById("ask-btn");
  const answer = document.getElementById("answer");
  if (!question.trim()) return;

  input.value = question;
  btn.disabled = true;
  answer.innerHTML = `<div class="answer"><p class="thinking">Routing to agents…</p></div>`;

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!res.ok) throw new Error(`Request failed (${res.status})`);
    renderAnswer(question, await res.json());
  } catch (err) {
    answer.innerHTML = `<div class="answer"><div class="error">${esc(err.message)}</div></div>`;
  } finally {
    btn.disabled = false;
  }
}

function wireAsk() {
  document.getElementById("ask-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitQuestion(document.getElementById("ask-input").value);
  });
  document.getElementById("suggestions").addEventListener("click", (e) => {
    const q = e.target.closest("button")?.dataset.q;
    if (q) submitQuestion(q);
  });
}

async function boot() {
  const main = document.getElementById("main");
  try {
    const res = await fetch("/api/dashboard");
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${res.status})`);
    }
    render(await res.json());
  } catch (err) {
    main.className = "";
    main.innerHTML = `<div class="error">${esc(err.message)}</div>`;
  }
}

boot();
