let currentPlan = null;

const $ = (selector) => document.querySelector(selector);
const today = new Date().toISOString().slice(0, 10);
$("#plan-start").value = today;
$("#restart-day").value = today;

function showError(message) {
  const box = $("#form-error");
  box.textContent = message;
  box.hidden = !message;
}

function setLoading(loading) {
  $("#loader").hidden = !loading;
  $("#create-button").disabled = loading;
}

function escapeHTML(text) {
  const element = document.createElement("span");
  element.textContent = String(text ?? "");
  return element.innerHTML;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(`${value}T12:00:00`));
}

function groupSchedule(schedule) {
  return schedule.reduce((groups, item) => {
    (groups[item.scheduled_date] ??= []).push(item);
    return groups;
  }, {});
}

function renderPlan(plan) {
  currentPlan = plan;
  $("#plan-output").hidden = false;
  $("#summary").textContent = plan.summary;
  const question = $("#clarifying-question");
  question.textContent = plan.clarifying_question ? `One useful follow-up: ${plan.clarifying_question}` : "";
  question.hidden = !plan.clarifying_question;

  $("#schedule").innerHTML = Object.entries(groupSchedule(plan.schedule)).map(([day, tasks]) => {
    const minutes = tasks.reduce((total, task) => total + task.estimated_minutes, 0);
    return `<article class="day"><div class="day-header"><time>${formatDate(day)}</time><span>${minutes} min</span></div>${tasks.map((task) => {
      const due = task.deadline ? ` · due ${escapeHTML(task.deadline)}` : "";
      return `<div class="task"><div class="task-title"><span class="score">P${task.priority_score}</span>${escapeHTML(task.title)}</div><p class="task-meta">${task.estimated_minutes} min${due}</p></div>`;
    }).join("")}</article>`;
  }).join("");

  $("#missed-tasks").innerHTML = plan.tasks.map((task) => `<label class="choice"><input type="checkbox" value="${escapeHTML(task.id)}"> ${escapeHTML(task.title)}</label>`).join("");
  renderExecutionActions(plan);
  $("#plan-output").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    const body = contentType.includes("application/json") ? await response.json() : {};
    const error = new Error(body.error || "Something went wrong. Please try again.");
    error.connectRequired = body.connect_required === true;
    throw error;
  }
  return contentType.includes("application/json") ? response.json() : response.blob();
}

function setExecutionStatus(message = "", isError = false) {
  const status = $("#execution-status");
  status.textContent = message;
  status.hidden = !message;
  status.classList.toggle("error", isError);
}

async function updateGoogleStatus() {
  const status = $("#google-status");
  const connect = $("#google-connect");
  try {
    const google = await api("/api/google/status");
    if (google.connected) {
      status.textContent = "Google account connected";
      status.classList.add("connected");
      connect.hidden = true;
    } else if (google.configured) {
      status.textContent = "Google account not connected";
      status.classList.remove("connected");
      connect.hidden = false;
    } else {
      status.textContent = "Google OAuth needs setup";
      status.classList.remove("connected");
      connect.hidden = false;
    }
  } catch (_) {
    status.textContent = "Google status unavailable";
    connect.hidden = true;
  }
}

async function performCalendar() {
  if (!currentPlan) return;
  const count = currentPlan.schedule.length;
  if (!window.confirm(`Create ${count} Google Calendar event${count === 1 ? "" : "s"}? This will write to your primary calendar.`)) return;
  setExecutionStatus("Creating calendar events…");
  try {
    const { created } = await api("/api/actions/calendar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: currentPlan.schedule, approved: true }) });
    setExecutionStatus(`Created ${created.length} calendar event${created.length === 1 ? "" : "s"}.`);
  } catch (error) {
    setExecutionStatus(error.message, true);
    if (error.connectRequired) updateGoogleStatus();
  }
}

async function performDocument(kind) {
  if (!currentPlan) return;
  const names = { pptx: "PowerPoint presentation", pdf: "PDF execution brief", docx: "Word execution report" };
  if (!window.confirm(`Generate the ${names[kind]} now?`)) return;
  setExecutionStatus(`Generating ${names[kind]}…`);
  try {
    const blob = await api("/api/actions/document", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan: currentPlan, kind, approved: true }) });
    downloadBlob(blob, { pptx: "focusflow-execution-plan.pptx", pdf: "focusflow-execution-brief.pdf", docx: "focusflow-execution-report.docx" }[kind]);
    setExecutionStatus(`${names[kind]} generated and downloaded.`);
  } catch (error) { setExecutionStatus(error.message, true); }
}

function emailCard(action) {
  const card = document.createElement("article");
  card.className = "action-card";
  const title = document.createElement("h3"); title.textContent = action.title || "Send an email";
  const description = document.createElement("p"); description.textContent = action.details || "Review and send this Gmail draft.";
  const recipient = document.createElement("input"); recipient.type = "email"; recipient.placeholder = "Recipient email"; recipient.value = action.recipient || "";
  const subject = document.createElement("input"); subject.placeholder = "Subject"; subject.value = action.subject || "";
  const body = document.createElement("textarea"); body.placeholder = "Email body"; body.value = action.body || "";
  const button = document.createElement("button"); button.type = "button"; button.textContent = "Approve & send Gmail";
  button.addEventListener("click", async () => {
    if (!window.confirm(`Send this email to ${recipient.value || "the entered recipient"}? You cannot undo sending it.`)) return;
    setExecutionStatus("Sending email…");
    try {
      const { message_id } = await api("/api/actions/email", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recipient: recipient.value, subject: subject.value, body: body.value, approved: true }) });
      setExecutionStatus(`Email sent successfully (message ${message_id.slice(0, 8)}…).`);
    } catch (error) {
      setExecutionStatus(error.message, true);
      if (error.connectRequired) updateGoogleStatus();
    }
  });
  card.append(title, description, recipient, subject, body, button);
  return card;
}

function documentCard(kind, title, description) {
  const card = document.createElement("article");
  card.className = "action-card";
  card.innerHTML = `<h3>${escapeHTML(title)}</h3><p>${escapeHTML(description)}</p>`;
  const button = document.createElement("button"); button.type = "button"; button.textContent = `Generate ${title}`;
  button.addEventListener("click", () => performDocument(kind));
  card.append(button);
  return card;
}

function renderExecutionActions(plan) {
  const container = $("#execution-actions");
  container.replaceChildren();
  setExecutionStatus("");
  const calendar = document.createElement("article");
  calendar.className = "action-card";
  calendar.innerHTML = `<h3>Create Google Calendar events</h3><p>Create ${plan.schedule.length} reviewed event${plan.schedule.length === 1 ? "" : "s"} in your primary Google Calendar.</p>`;
  const calendarButton = document.createElement("button"); calendarButton.type = "button"; calendarButton.textContent = "Approve & create events";
  calendarButton.addEventListener("click", performCalendar); calendar.append(calendarButton); container.append(calendar);

  const emails = (plan.actions || []).filter((action) => action.type === "email");
  emails.forEach((action) => container.append(emailCard(action)));
  container.append(documentCard("pptx", "PowerPoint", "A presentation summarising the execution plan and daily focus blocks."));
  container.append(documentCard("pdf", "PDF brief", "A shareable PDF version of the scheduled execution plan."));
  container.append(documentCard("docx", "Word report", "An editable Word report of tasks and planned work."));
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

async function loadHistory() {
  const container = $("#history-list");
  try {
    const { plans } = await api("/api/plans");
    if (!plans.length) {
      container.innerHTML = '<p class="muted">No saved plans yet.</p>';
      return;
    }
    container.innerHTML = plans.map((plan) => `<button class="history-item" data-plan-id="${plan.id}">${escapeHTML(plan.title)}<small>${formatDate(plan.created_at.slice(0, 10))}</small></button>`).join("");
    container.querySelectorAll("[data-plan-id]").forEach((button) => button.addEventListener("click", async () => {
      try {
        const { plan } = await api(`/api/plans/${button.dataset.planId}`);
        renderPlan(plan);
      } catch (error) { showError(error.message); }
    }));
  } catch (_) {
    container.innerHTML = '<p class="muted">Saved plans are unavailable right now.</p>';
  }
}

$("#planner-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  const request = $("#request").value.trim();
  if (!request) return showError("Describe your workload first.");
  setLoading(true);
  try {
    const { plan } = await api("/api/plans", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, hours_per_day: Number($("#hours").value), plan_start: $("#plan-start").value }),
    });
    renderPlan(plan);
    loadHistory();
  } catch (error) {
    showError(error.message);
  } finally { setLoading(false); }
});

$("#download-checklist").addEventListener("click", async () => {
  if (!currentPlan) return;
  try { downloadBlob(await api("/api/exports/checklist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan: currentPlan }) }), "focusflow-checklist.md"); }
  catch (error) { showError(error.message); }
});

$("#download-calendar").addEventListener("click", async () => {
  if (!currentPlan) return;
  try { downloadBlob(await api("/api/exports/calendar", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: currentPlan.schedule }) }), "focusflow-plan.ics"); }
  catch (error) { showError(error.message); }
});

$("#replan-button").addEventListener("click", async () => {
  if (!currentPlan) return;
  const missed_ids = [...document.querySelectorAll("#missed-tasks input:checked")].map((input) => input.value);
  showError(""); setLoading(true);
  try {
    const { plan } = await api("/api/replan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan: currentPlan, missed_ids, restart_day: $("#restart-day").value }) });
    renderPlan(plan); loadHistory();
  } catch (error) { showError(error.message); }
  finally { setLoading(false); }
});

const pageParams = new URLSearchParams(window.location.search);
if (pageParams.get("google_connected")) {
  setExecutionStatus("Google account connected. You can now approve Calendar and Gmail actions.");
}
if (pageParams.get("auth_error")) {
  setExecutionStatus(pageParams.get("auth_error"), true);
}
loadHistory();
updateGoogleStatus();
