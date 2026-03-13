async function load() {
  const [healthResp, runsResp] = await Promise.all([
    fetch("/health"),
    fetch("/runs"),
  ]);

  const health = await healthResp.json();
  const runs = await runsResp.json();

  document.getElementById("health").textContent = health.status;
  const runsEl = document.getElementById("runs");
  if (runs.length === 0) {
    runsEl.textContent = "No runs yet.";
    return;
  }
  runsEl.innerHTML = runs.map(
    (run) => `<div class="run"><strong>${run.title}</strong><div class="state">${run.state}</div></div>`
  ).join("");
}

load().catch((error) => {
  document.getElementById("health").textContent = `error: ${error}`;
});
