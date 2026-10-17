"use strict";

const POLL_MS = 2000;
const el = (id) => document.getElementById(id);
const panelBridge = window.webkit && window.webkit.messageHandlers ? window.webkit.messageHandlers.echoPanel : null;
let muted = false;
let promptDirty = false;

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error((data && data.error) || response.statusText);
  return data;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function ago(epochSeconds) {
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function minutes(seconds) {
  return seconds >= 60 ? `${Math.round(seconds / 60)} min` : `${Math.round(seconds)} s`;
}

function renderSessions(sessions) {
  const list = el("sessions");
  list.replaceChildren();
  if (!sessions.length) {
    list.append(node("li", "empty", "No Claude Code sessions running."));
    return;
  }
  for (const session of sessions) {
    const item = node("li", "session");
    item.title = session.last_headline || session.cwd;
    const dot = node("span", `dot ${session.status}`);
    dot.setAttribute("aria-label", session.status);
    item.append(dot, node("span", "sign", session.call_sign), node("span", "project", session.project));
    list.append(item);
  }
}

function renderEchoes(echoes) {
  const list = el("echoes");
  list.replaceChildren();
  if (!echoes.length) {
    list.append(node("li", "empty", "Nothing yet. Long turns are echoed when they finish."));
    return;
  }
  for (const echo of echoes) {
    const item = node("li", "echo");
    const meta = node("div", "echo-meta");
    meta.append(node("span", "sign", echo.call_sign),
      document.createTextNode(`${echo.project} · ${minutes(echo.duration_seconds)} · ${echo.tool_calls} tools · ${ago(echo.created_at)}`));
    if (echo.kb && echo.kb.relevant) {
      const badge = node("span", "kb-badge", "KB");
      badge.title = echo.kb.context;
      meta.append(badge);
    }
    const text = node("div", echo.error ? "echo-text error" : "echo-text", echo.headline || `Failed: ${echo.error}`);
    item.append(meta, text);
    if (echo.spoken_text) {
      const replay = node("button", "replay", "▶");
      replay.type = "button";
      replay.title = "Say it again";
      replay.setAttribute("aria-label", `Replay echo from ${echo.call_sign}`);
      replay.addEventListener("click", () => api("POST", `/api/echoes/${echo.id}/replay`, {}).catch(showError));
      item.append(replay);
    }
    list.append(item);
  }
}

function renderFooter(state) {
  const footer = el("footer");
  footer.replaceChildren();
  footer.append(node("span", "", `Echo when ≥ ${minutes(state.thresholds.min_turn_seconds)} and ≥ ${state.thresholds.min_tool_calls} tool calls`));
  footer.append(node("span", "", `Voice: ${state.voice}`));
  const kb = state.kb || {};
  const kbText = kb.state === "error" ? `KB: ${kb.error}` : `KB: ${kb.state || "unknown"}`;
  footer.append(node("span", kb.state === "error" ? "warn" : "", kbText));
}

function renderMute() {
  const button = el("muteButton");
  button.textContent = muted ? "🔇" : "🔊";
  button.classList.toggle("is-on", muted);
  button.title = muted ? "Unmute speech" : "Mute speech";
  button.setAttribute("aria-label", button.title);
}

async function refresh() {
  try {
    const state = await api("GET", "/api/state");
    muted = state.muted;
    el("liveCount").textContent = `${state.sessions.length} live`;
    renderMute();
    renderSessions(state.sessions);
    renderEchoes(state.echoes);
    renderFooter(state);
  } catch (error) {
    el("liveCount").textContent = "offline";
  }
}

function showError(error) {
  el("promptStatus").textContent = error.message;
}

async function openPrompt() {
  const card = el("promptCard");
  if (!card.classList.contains("hidden")) {
    card.classList.add("hidden");
    return;
  }
  const { prompt } = await api("GET", "/api/prompt");
  el("promptInput").value = prompt;
  el("promptStatus").textContent = "Applies to the next echo";
  promptDirty = false;
  card.classList.remove("hidden");
  el("promptInput").focus();
}

async function savePrompt() {
  const button = el("promptSave");
  button.disabled = true;
  try {
    await api("PUT", "/api/prompt", { prompt: el("promptInput").value });
    el("promptStatus").textContent = "Saved";
    promptDirty = false;
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = false;
  }
}

el("muteButton").addEventListener("click", async () => {
  muted = !muted;
  renderMute();
  await api("POST", "/api/mute", { muted }).catch(() => refresh());
});
el("promptButton").addEventListener("click", () => openPrompt().catch(showError));
el("promptCancel").addEventListener("click", () => el("promptCard").classList.add("hidden"));
el("promptSave").addEventListener("click", savePrompt);
el("promptInput").addEventListener("input", () => {
  promptDirty = true;
  el("promptStatus").textContent = "Unsaved";
});
el("promptInput").addEventListener("keydown", (event) => {
  if (event.key === "s" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    savePrompt();
  }
});

if (panelBridge) {
  el("closeButton").classList.remove("hidden");
  el("closeButton").addEventListener("click", () => panelBridge.postMessage("hide"));
} else {
  document.body.classList.add("in-browser");
}

window.addEventListener("beforeunload", (event) => {
  if (promptDirty) event.preventDefault();
});

refresh();
setInterval(refresh, POLL_MS);
