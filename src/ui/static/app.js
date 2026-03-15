const state = {
  runs: [],
  selectedRunId: null,
};

function byId(id) {
  return document.getElementById(id);
}

function setActivity(message) {
  byId("activity").textContent = message;
}

function renderRunOptions() {
  const select = byId("task-run-id");
  if (state.runs.length === 0) {
    select.innerHTML = '<option value="">No runs available</option>';
    select.disabled = true;
    return;
  }

  select.disabled = false;
  select.innerHTML = state.runs.map((run) => {
    const selected = run.id === state.selectedRunId ? " selected" : "";
    return `<option value="${run.id}"${selected}>${run.title} (${run.state})</option>`;
  }).join("");
}

function renderRuns() {
  const runsEl = byId("runs");
  if (state.runs.length === 0) {
    runsEl.textContent = "No runs yet.";
    return;
  }

  runsEl.innerHTML = state.runs.map((run) => {
    const selectedClass = run.id === state.selectedRunId ? " selected" : "";
    return `
      <button class="run${selectedClass}" type="button" data-run-id="${run.id}">
        <strong>${run.title}</strong>
        <div class="state">${run.state}</div>
        <div class="meta">${run.id}</div>
      </button>
    `;
  }).join("");

  for (const button of runsEl.querySelectorAll("[data-run-id]")) {
    button.addEventListener("click", async () => {
      state.selectedRunId = button.dataset.runId;
      renderRuns();
      renderRunOptions();
      await loadRunDetail();
    });
  }
}

function renderHealth(health) {
  byId("health").textContent = health.status;
}

function renderRunDetail(detail) {
  const target = byId("run-detail");
  if (!detail) {
    target.textContent = "No run selected.";
    return;
  }

  const tasks = detail.tasks.length === 0
    ? "<div>No tasks yet.</div>"
    : detail.tasks.map((task) => `
        <div class="task-row">
          <strong>${task.name}</strong>
          <div class="state">${task.state}</div>
          <div class="meta">${task.id}</div>
        </div>
      `).join("");

  target.innerHTML = `
    <div><strong>${detail.run.title}</strong></div>
    <div class="state">${detail.run.state}</div>
    <div class="meta">${detail.run.id}</div>
    <div class="task-list">${tasks}</div>
  `;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data.error || response.statusText;
    throw new Error(error);
  }
  return data;
}

async function loadRunsAndHealth() {
  const [health, runs] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/runs"),
  ]);

  state.runs = runs;
  if (!state.selectedRunId && runs.length > 0) {
    state.selectedRunId = runs[0].id;
  }
  if (state.selectedRunId && !runs.some((run) => run.id === state.selectedRunId)) {
    state.selectedRunId = runs[0]?.id || null;
  }

  renderHealth(health);
  renderRuns();
  renderRunOptions();
}

async function loadRunDetail() {
  if (!state.selectedRunId) {
    renderRunDetail(null);
    return;
  }

  const detail = await fetchJson(`/ui/api/runs/${state.selectedRunId}/detail`);
  renderRunDetail(detail);
}

async function refreshAll() {
  await loadRunsAndHealth();
  await loadRunDetail();
}

async function handleCreateRun(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const title = byId("run-title").value.trim();
    const payload = title ? { title } : {};
    const created = await fetchJson("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.selectedRunId = created.id;
    byId("create-run-form").reset();
    setActivity(`Created run ${created.id}.`);
    await refreshAll();
  } catch (error) {
    setActivity(`Create run failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function handleCreateTask(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const runId = byId("task-run-id").value;
    const name = byId("task-name").value.trim();
    const maxRetries = Number(byId("task-max-retries").value || "3");
    if (!runId) {
      throw new Error("select_a_run");
    }
    if (!name) {
      throw new Error("task_name_required");
    }

    state.selectedRunId = runId;
    const created = await fetchJson(`/runs/${runId}/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, max_retries: maxRetries }),
    });
    byId("task-name").value = "";
    setActivity(`Created task ${created.name} in state ${created.state}.`);
    await refreshAll();
  } catch (error) {
    setActivity(`Add task failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

async function handleDrainWorker() {
  const button = byId("drain-worker");
  button.disabled = true;
  try {
    const result = await fetchJson("/workers/drain-once", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    byId("worker-status").textContent = JSON.stringify(result, null, 2);
    setActivity(`Worker result: ${result.status}.`);
    await refreshAll();
  } catch (error) {
    byId("worker-status").textContent = `error: ${error.message}`;
    setActivity(`Worker action failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

function wireEvents() {
  byId("create-run-form").addEventListener("submit", handleCreateRun);
  byId("create-task-form").addEventListener("submit", handleCreateTask);
  byId("drain-worker").addEventListener("click", handleDrainWorker);
}

wireEvents();
refreshAll().catch((error) => {
  byId("health").textContent = `error: ${error.message}`;
  setActivity(`Initial load failed: ${error.message}`);
});
