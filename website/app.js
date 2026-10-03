const EMBEDDED = new URLSearchParams(location.search).get('embedded') === '1';
if (EMBEDDED) document.documentElement.classList.add('embedded-mode');
const AGENT_URL = EMBEDDED ? '' : 'http://127.0.0.1:8765';
const $ = (id) => document.getElementById(id);

let dates = [];
let priorityCache = {times: [], venues: []};
let state = null;
let testPassed = false;
let lastSelection = [];
let agentToken = localStorage.getItem('saveetha_agent_token') || '';

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
}

function authHeaders() {
  return agentToken ? {"X-Agent-Token": agentToken} : {};
}

function renderDates() {
  $("dateList").innerHTML = dates.length
    ? dates.map((d, i) => `<span class="chip"><span>${escapeHtml(d)}</span><button onclick="removeDate(${i})" aria-label="Remove date">×</button></span>`).join("")
    : `<span class="date-empty">No dates added yet</span>`;
}
window.removeDate = (i) => {
  dates.splice(i, 1);
  testPassed = false;
  $("start").disabled = true;
  renderDates();
};

function priorityControl(container, items, preserve=true) {
  const el = $(container);
  const key = container === "times" ? "times" : "venues";
  const incoming = [...new Set(items || [])];
  const existing = preserve ? priorityCache[key].filter(x => incoming.includes(x)) : [];
  const additions = incoming.filter(x => !existing.includes(x));
  priorityCache[key] = [...existing, ...additions];
  el.innerHTML = "";
  if (!priorityCache[key].length) {
    el.innerHTML = `<div class="priority-empty">No options detected yet.</div>`;
    return;
  }
  priorityCache[key].forEach((item, i) => {
    const row = document.createElement("div"); row.className = "priority-item";
    row.innerHTML = `<div class="priority-label"><span class="priority-index">${i + 1}</span><span>${escapeHtml(item)}</span></div><div class="move"><button aria-label="Move up" ${i === 0 ? "disabled" : ""}>↑</button><button aria-label="Move down" ${i === priorityCache[key].length - 1 ? "disabled" : ""}>↓</button></div>`;
    row.children[1].children[0].onclick = () => move(container, i, -1);
    row.children[1].children[1].onclick = () => move(container, i, 1);
    el.appendChild(row);
  });
}

function currentPriority(container) {
  return [...$(container).querySelectorAll(".priority-item .priority-label > span:last-child")].map(x => x.textContent);
}

function move(container, i, delta) {
  const key = container === "times" ? "times" : "venues";
  const arr = [...priorityCache[key]];
  const j = i + delta;
  if (j < 0 || j >= arr.length) return;
  [arr[i], arr[j]] = [arr[j], arr[i]];
  priorityCache[key] = arr;
  priorityControl(container, arr, false);
  testPassed = false;
  $("start").disabled = true;
}

function setStatus(status) {
  const b = $("statusBadge");
  const clean = status || "logged_out";
  b.textContent = clean.replaceAll("_", " ").toUpperCase();
  b.className = "status " + clean;
}

function renderState(s) {
  state = s;
  setStatus(s.status || "logged_out");
  const loggedIn = !!s.logged_in;
  if (!loggedIn) {
    $("agentConnect").classList.remove("hidden");
    $("loginView").classList.remove("hidden");
    $("appView").classList.add("hidden");
    return;
  }
  // The local-agent connection card is only needed before the Saveetha login session.
  $("agentConnect").classList.add("hidden");
  $("loginView").classList.add("hidden");
  $("appView").classList.remove("hidden");

  const events = s.events || [];
  const previousEvent = $("event").value;
  $("event").innerHTML = events.length
    ? events.map(x => `<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join("")
    : `<option>Run a scan first</option>`;
  $("event").disabled = !events.length;
  if (events.length && events.includes(previousEvent)) $("event").value = previousEvent;
  priorityControl("times", s.times || [], true);
  priorityControl("venues", s.venues || [], true);
  $("test").disabled = !events.length;
  $("stop").disabled = !["booking"].includes(s.status);

  if (s.status === "completed") {
    testPassed = false;
    $("start").disabled = true;
  }
}

async function api(path, options = {}) {
  const headers = {...authHeaders(), ...(options.headers || {})};
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const r = await fetch(AGENT_URL + path, {...options, headers});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || data.error || "Request failed");
  return data;
}

async function connectAgent() {
  const token = $("agentToken").value.trim();
  if (!token) return alert("Paste the Agent token shown in the local agent window.");
  agentToken = token;
  localStorage.setItem('saveetha_agent_token', agentToken);
  try {
    const h = await api('/api/health', {cache:'no-store'});
    $("agentError").textContent = "Connected to local agent.";
    $("agentStatus").textContent = `Connected · ${h.status.replaceAll('_',' ')}`;
    $("loginView").classList.remove("hidden");
    $("agentConnect").classList.add("connected");
  } catch (e) {
    localStorage.removeItem('saveetha_agent_token');
    agentToken = '';
    $("agentError").textContent = "Could not connect to the local agent. Start the Saveetha Agent application and try again.";
    $("agentStatus").textContent = "Agent not connected";
  }
}

$("connectAgent").onclick = connectAgent;
$("clearAgent").onclick = () => {
  agentToken = '';
  localStorage.removeItem('saveetha_agent_token');
  $("agentToken").value = '';
  $("agentStatus").textContent = 'Agent not connected';
  $("agentConnect").classList.remove('connected');
  $("loginView").classList.add('hidden');
  $("appView").classList.add('hidden');
};

async function refreshState() {
  if (!agentToken) return;
  try {
    const s = await api("/api/state", {cache:'no-store'});
    renderState(s);
  } catch {}
}

async function refreshLogs() {
  if (!agentToken) return;
  try {
    const data = await api("/api/logs", {cache:'no-store'});
    $("logs").textContent = data.logs.join("\n");
    $("logs").scrollTop = $("logs").scrollHeight;
  } catch {}
}

$("togglePassword").onclick = () => {
  const input = $("password");
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  $("togglePassword").textContent = showing ? "Show" : "Hide";
};

$("loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const button = $("loginButton");
  const error = $("loginError");
  error.textContent = "";
  button.disabled = true;
  button.textContent = "Signing in…";
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({username: $("username").value.trim(), password: $("password").value})
    });
    $("password").value = "";
    renderState(data.state);
    $("agentConnect").classList.add("hidden");
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
    button.textContent = "Sign in securely";
  }
};

$("event").addEventListener("change", () => {
  priorityCache.times = [];
  priorityCache.venues = [];
  if (state) {
    priorityControl("times", state.times || [], false);
    priorityControl("venues", state.venues || [], false);
  }
  testPassed = false;
  $("start").disabled = true;
});

$("logout").onclick = async () => {
  if (!confirm("Log out and close the Saveetha browser session?")) return;
  await api("/api/logout", {method:"POST"}).catch(() => {});
  $("agentConnect").classList.remove("hidden");
  dates = [];
  renderDates();
  testPassed = false;
  $("start").disabled = true;
  $("username").value = "";
  $("password").value = "";
  refreshState();
};

$("addDate").onclick = () => {
  const d = $("dates").value;
  if (!d) return;
  if (!dates.includes(d)) dates.push(d);
  dates.sort();
  testPassed = false;
  $("start").disabled = true;
  renderDates();
};

$("preview").onclick = async () => {
  if (!dates.length) return alert("Add at least one booking date.");
  testPassed = false;
  $("start").disabled = true;
  $("preview").disabled = true;
  $("preview").textContent = "Scanning…";
  try {
    const data = await api("/api/preview", {method:"POST", body:JSON.stringify({dates})});
    renderState(data.state);
  } catch (e) {
    alert(e.message);
  } finally {
    $("preview").disabled = false;
    $("preview").innerHTML = "Scan available sessions <span>→</span>";
  }
};

$("test").onclick = async () => {
  try {
    const data = await api("/api/test-selection", {
      method:"POST",
      body:JSON.stringify({event:$("event").value, times:currentPriority("times"), venues:currentPriority("venues"), slots_per_date:Number($("slotsPerDate").value)})
    });
    lastSelection = data.selected || [];
    $("selection").className = "selection" + (lastSelection.length ? "" : " empty");
    $("selection").innerHTML = lastSelection.length
      ? lastSelection.map((s, i) => `<div class="slot"><div class="slot-no">${i + 1}</div><div class="slot-main"><strong>${escapeHtml(s.date)} · ${escapeHtml(s.title)}</strong><span>${escapeHtml(s.session)} · ${escapeHtml(s.duration)} min · Venue ${escapeHtml(s.venue)}</span></div><div class="slot-status ${String(s.status).toLowerCase().replaceAll(" ", "-")}">${escapeHtml(s.status)}</div></div>`).join("")
      : "No matching published sessions.";
    testPassed = lastSelection.length > 0;
    $("start").disabled = !testPassed;
    setStatus("tested");
  } catch (e) {
    alert(e.message);
  }
};

$("start").onclick = async () => {
  if (!testPassed) return;
  const confirmed = confirm("Start ACTUAL booking attempts now?\n\nOnly enabled Book Now slots matching your tested configuration will be attempted.");
  if (!confirmed) return;

  $("start").disabled = true;
  $("stop").disabled = false;
  try {
    await api("/api/start-booking", {
      method:"POST",
      body:JSON.stringify({
        dates,
        event:$("event").value,
        times:currentPriority("times"),
        venues:currentPriority("venues"),
        slots_per_date:Number($("slotsPerDate").value),
        purpose:$("purpose").value || "CIA",
        monitor:$("monitor").checked,
        retry:Number($("retry").value),
        confirmed:true
      })
    });
    setStatus("booking");
  } catch (e) {
    alert(e.message);
    $("start").disabled = false;
  }
};

$("stop").onclick = async () => {
  await api("/api/stop", {method:"POST"}).catch(e => alert(e.message));
};

async function initializeAgent() {
  if (EMBEDDED) {
    $("agentConnect").classList.add("hidden");
    $("embeddedHint").classList.remove("hidden");
    try {
      const boot = await fetch("/api/bootstrap", {cache:"no-store"}).then(r => r.json());
      agentToken = boot.agent_token;
      localStorage.setItem("saveetha_agent_token", agentToken);
      $("loginView").classList.remove("hidden");
      await refreshState();
    } catch {
      $("loginError").textContent = "The local agent UI is not available.";
    }
    return;
  }
  if (agentToken) {
    $("agentToken").value = agentToken;
    connectAgent();
  } else {
    $("loginView").classList.add("hidden");
    $("appView").classList.add("hidden");
  }
}

renderDates();
initializeAgent();
setInterval(refreshState, 1000);
setInterval(refreshLogs, 800);
setInterval(async () => {
  if (!agentToken) return;
  try {
    const h = await api('/api/health', {cache:'no-store'});
    document.body.dataset.agent = 'online';
    $("agentStatus").textContent = `Connected · ${h.status.replaceAll('_',' ')}`;
  } catch {
    document.body.dataset.agent = 'offline';
    $("agentStatus").textContent = 'Agent offline';
  }
}, 3000);
