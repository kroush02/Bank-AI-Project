"use strict";
const $ = (id) => document.getElementById(id);
const examples = {
  totals: "Show each customer's ID, name, and total completed transaction amount in EGP for September 2026, only customers whose total is more than 5000 EGP, highest total first.",
  transactions: "List customer names and cities with their completed EGP debit transactions in September 2026. Include transaction ID, date and amount in EGP, ordered by date.",
  inactive: "List the IDs and names of all customers who have no completed transactions in September 2026, in any currency. Order by customer ID."
};
const labels = { pending: "Queued", in_progress: "Running", completed: "Published", failed: "Stopped", needs_clarification: "Needs detail" };
let configuration = null;
let selectedId = null;
let busy = false;
let polling = null;
let reportLoaded = null;
const token = document.querySelector('meta[name="studio-token"]').content;

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The server could not complete this request.");
  return data;
}
function showError(message) { $("request-error").textContent = message; $("request-error").hidden = !message; }
function updateCount() { $("character-count").textContent = `${$("request").value.length.toLocaleString()} / 8,000`; }
function setBusy(value) {
  busy = value;
  $("generate").disabled = value || !configuration?.ready;
  $("request").disabled = value;
  $("generate").firstElementChild.textContent = value ? "Generating report…" : "Generate report";
  document.querySelectorAll("[data-example], #new-request, .history-item").forEach(b => b.disabled = value);
  document.querySelector(".result-panel").setAttribute("aria-busy", String(value));
}
function setStages(trace = []) {
  document.querySelectorAll("#stages li").forEach((element, index) => {
    const step = [...trace].reverse().find(s => s.agent === element.dataset.stage);
    let state = "", text = "Waiting", mark = String(index + 1);
    if (step?.status === "running") { state = "running"; text = "Working"; }
    else if (["failed", "needs_clarification"].includes(step?.status)) { state = "failed"; text = "Stopped"; mark = "!"; }
    else if (step) { state = "done"; text = "Done"; mark = "✓"; }
    element.className = state;
    element.querySelector(".stage-state").textContent = text;
    element.querySelector(".stage-mark").textContent = mark;
  });
}
function emptyReport(title, description) {
  $("report-content").hidden = true;
  $("empty-report").hidden = false;
  $("empty-title").textContent = title;
  $("empty-description").textContent = description;
}
function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
async function renderReport(ticket) {
  const root = `/reports/${encodeURIComponent(ticket.id)}`;
  const [data, metadata] = await Promise.all([api(`${root}/data.json`), api(`${root}/metadata.json`)]);
  if (selectedId !== ticket.id) return;
  $("report-request").textContent = ticket.request;
  $("row-count").textContent = data.rows.length.toLocaleString();
  $("published-time").textContent = formatDate(metadata.generated_at_utc);
  $("preview-count").textContent = `${Math.min(50, data.rows.length)} of ${data.rows.length.toLocaleString()} rows`;
  const head = document.createElement("tr");
  data.columns.forEach(name => { const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = name; head.append(cell); });
  $("data-table").querySelector("thead").replaceChildren(head);
  const body = document.createDocumentFragment();
  data.rows.slice(0, 50).forEach(row => {
    const tr = document.createElement("tr");
    row.forEach(value => {
      const cell = document.createElement("td");
      if (typeof value === "number") cell.className = "numeric";
      cell.textContent = value === null ? "—" : String(value);
      tr.append(cell);
    });
    body.append(tr);
  });
  $("data-table").querySelector("tbody").replaceChildren(body);
  $("empty-data").hidden = data.rows.length !== 0;
  $("report-path").textContent = ticket.report_path;
  $("review-reason").textContent = metadata.validation.semantic_review;
  $("sql").textContent = metadata.sql;
  $("parameters").textContent = JSON.stringify(metadata.parameters, null, 2);
  $("open-report").href = `${root}/report.html`;
  const files = { "download-csv": "data.csv", "download-json": "data.json", "download-bundle": "bundle.zip", "download-metadata": "metadata.json" };
  Object.entries(files).forEach(([id, name]) => { $(id).href = `/download/${encodeURIComponent(ticket.id)}/${name}`; });
  $("empty-report").hidden = true;
  $("report-content").hidden = false;
  reportLoaded = ticket.id;
}
async function showTicket(ticket) {
  selectedId = ticket.id;
  localStorage.setItem("bank-studio-ticket", ticket.id);
  $("report-badge").textContent = labels[ticket.status] || ticket.status;
  $("report-badge").className = `badge ${ticket.status === "completed" ? "published" : ["failed", "needs_clarification"].includes(ticket.status) ? "failed" : ""}`;
  setStages(ticket.trace);
  $("run-status").textContent = labels[ticket.status] || ticket.status;
  const running = ["pending", "in_progress"].includes(ticket.status);
  setBusy(running && ticket.worker_active);
  if (running) {
    if (ticket.worker_active) {
      emptyReport("Your agents are on it.", "Follow their progress on the left. Your report will appear here after validation and publication.");
    } else {
      emptyReport("Waiting for this ticket’s worker.", "This server does not own the ticket. A CLI worker may still be processing it. You can start a new request if its earlier worker has stopped.");
    }
    polling = setTimeout(() => poll(ticket.id), 800);
  } else if (ticket.status === "completed") {
    showError("");
    if (reportLoaded !== ticket.id) {
      emptyReport("Opening your report…", "Reading the published files.");
      try { await renderReport(ticket); }
      catch (error) { emptyReport("Report files unavailable.", error.message); throw error; }
    }
  } else {
    showError(ticket.error || "Add more detail to your request, then try again.");
    emptyReport(ticket.status === "needs_clarification" ? "A little more detail, please." : "This report could not finish.", ticket.error || "Edit the request and try again.");
  }
}
async function poll(id) {
  if (selectedId !== id) return;
  try {
    const ticket = await api(`/api/tickets/${encodeURIComponent(id)}`);
    await showTicket(ticket);
    if (!["pending", "in_progress"].includes(ticket.status)) await loadHistory();
  } catch (error) {
    setBusy(false);
    showError(`${error.message} Reload the page to reconnect. A running request can continue on the server.`);
  }
}
async function loadHistory() {
  const tickets = await api("/api/tickets");
  $("no-history").hidden = tickets.length !== 0;
  const items = document.createDocumentFragment();
  tickets.forEach(ticket => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `history-item ${selectedId === ticket.id ? "selected" : ""}`;
    button.disabled = busy;
    const text = document.createElement("span"); text.className = "history-text";
    const title = document.createElement("strong"); title.textContent = ticket.request;
    const date = document.createElement("small"); date.textContent = `${formatDate(ticket.created_at)} · ${ticket.id.slice(0, 8)}`;
    text.append(title, date);
    const badge = document.createElement("span"); badge.className = `badge ${ticket.status === "completed" ? "published" : ""}`; badge.textContent = labels[ticket.status];
    const arrow = document.createElement("span"); arrow.className = "history-arrow"; arrow.textContent = "↗"; arrow.setAttribute("aria-hidden", "true");
    button.append(text, badge, arrow);
    button.addEventListener("click", async () => {
      clearTimeout(polling); showError(""); reportLoaded = null;
      $("request").value = ticket.request; updateCount();
      try { await showTicket(await api(`/api/tickets/${ticket.id}`)); await loadHistory(); }
      catch (error) { showError(error.message); }
    });
    items.append(button);
  });
  $("history-list").replaceChildren(items);
  return tickets;
}
$("request").addEventListener("input", updateCount);
document.querySelectorAll("[data-example]").forEach(button => button.addEventListener("click", () => {
  $("request").value = examples[button.dataset.example]; updateCount(); $("request").focus();
}));
$("request-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  const request = $("request").value.trim();
  if (!request) { showError("Enter a request before you generate a report."); $("request").focus(); return; }
  showError(""); clearTimeout(polling); reportLoaded = null; setBusy(true); setStages();
  try {
    const ticket = await api("/api/tickets", { method: "POST", headers: { "Content-Type": "application/json", "X-Studio-Token": token }, body: JSON.stringify({ request }) });
    selectedId = ticket.id;
    await showTicket(await api(`/api/tickets/${ticket.id}`));
    await loadHistory();
  } catch (error) { setBusy(false); showError(error.message); }
});
$("new-request").addEventListener("click", () => {
  if (busy) return;
  clearTimeout(polling); selectedId = null; reportLoaded = null; localStorage.removeItem("bank-studio-ticket");
  $("request").value = ""; updateCount(); showError(""); setStages();
  $("report-badge").textContent = "No report yet"; $("report-badge").className = "badge";
  $("run-status").textContent = "Ready when you are";
  emptyReport("A clear answer, ready to share.", "Your published report will appear here. Start with a question or choose an example.");
  loadHistory().catch(error => showError(error.message)); $("request").focus();
});
async function start() {
  try {
    configuration = await api("/api/status");
    $("configuration-error").textContent = configuration.problem || "";
    $("configuration-error").hidden = configuration.ready;
    setBusy(false);
    const tickets = await loadHistory();
    const stored = localStorage.getItem("bank-studio-ticket");
    const selected = tickets.find(t => t.id === configuration.active_ticket) || tickets.find(t => t.id === stored);
    if (selected) { $("request").value = selected.request; updateCount(); await showTicket(selected); }
  } catch (error) {
    setBusy(false); showError(`${error.message} Start the local server, then reload this page.`);
  }
}
start();
