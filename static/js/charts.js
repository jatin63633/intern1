const charts = {};
const PALETTE = ["#0a6c8a", "#e08a1e", "#3aa675", "#c0392b", "#7c5cbf", "#2a9d8f", "#d1495b", "#6b7f99"];

async function getJSON(url, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null)).toString();
  const res = await fetch(qs ? `${url}?${qs}` : url, { headers: { "X-Requested-With": "fetch" } });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return res.json();
}

function draw(id, type, labels, datasets, opts = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  if (charts[id]) charts[id].destroy();
  datasets.forEach((d, i) => {
    const c = PALETTE[i % PALETTE.length];
    if (type === "doughnut") d.backgroundColor = labels.map((_, k) => PALETTE[k % PALETTE.length]);
    else { d.backgroundColor = d.backgroundColor || c; d.borderColor = d.borderColor || c; }
    if (type === "line") { d.pointRadius = 2; d.tension = 0.25; d.borderWidth = 2; }
  });
  const scales = type === "doughnut" ? {} : { y: { beginAtZero: true, title: { display: !!opts.yTitle, text: opts.yTitle || "" } } };
  charts[id] = new Chart(el, { type, data: { labels, datasets },
    options: Object.assign({ responsive: true, maintainAspectRatio: false, scales,
      plugins: { legend: { display: datasets.length > 1 || type === "doughnut", position: "bottom" } } }, opts.chart || {}) });
}

function filters() {
  const p = new URLSearchParams(window.location.search);
  return { department: p.get("department") || "", start: p.get("start") || "", end: p.get("end") || "" };
}

async function loadAnalytics(ids) {
  const d = await getJSON("/api/analytics", filters());
  if (d.empty) return;
  const bar = (id, o, label, y, horizontal) => o && ids.includes(id) &&
    draw(id, "bar", o.labels, [{ label, data: o.values }], { yTitle: y, chart: horizontal ? { indexAxis: "y", scales: { x: { beginAtZero: true } } } : {} });
  if (ids.includes("occupancy")) draw("occupancy", "line", d.occupancy.labels, d.occupancy.datasets, { yTitle: "Avg occupied beds" });
  if (ids.includes("diagnosis")) draw("diagnosis", "doughnut", d.diagnosis.labels, [{ data: d.diagnosis.values }]);
  bar("los_dept", d.los_dept, "Avg length of stay (days)", "Days");
  bar("los_hist", d.los_hist, "Stays", "Discharges");
  bar("trend", d.trend, "Admissions", "Admissions");
  bar("age", d.age, "Patients", "Patients");
  bar("readmit_dept", d.readmit_dept, "30-day readmission %", "%");
  bar("readmit_dx", d.readmit_dx, "30-day readmission %", "%", true);
  bar("readmit_age", d.readmit_age, "30-day readmission %", "%");
}
