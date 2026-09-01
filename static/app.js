"use strict";

// 状態を <html> の data-* 属性と data-slot のテキストに転写する。
// 見た目の分岐は app.css 側に持たせ、このファイルはクラス名を参照しない。

const POLL_INTERVAL = 2000;
const VOLUME_THROTTLE = 200;
const VOLUME_STEP = 5;
const WAKE_THROTTLE = 1000;

const root = document.documentElement;
const slots = {};
document.querySelectorAll("[data-slot]").forEach((el) => {
  slots[el.dataset.slot] = el;
});

let current = null;
let lastRev = null;
let assetsRev = null;
let scenario = "";
let volumeTimer = null;
let pendingVolume = null;
let lastWake = 0;
let pollTimer = null;

function setText(name, value) {
  const el = slots[name];
  if (el && el.textContent !== value) {
    el.textContent = value;
  }
}

function render(state) {
  current = state;

  root.dataset.status = state.status;
  root.dataset.muted = String(state.muted);
  root.dataset.art = state.art ? "yes" : "no";
  root.dataset.conn = state.conn;

  setText("title", state.title);
  setText("artist", state.artist);
  setText("album", state.album);
  setText("vol", String(state.vol));

  if (slots.art && slots.art.getAttribute("src") !== state.art) {
    if (state.art) {
      slots.art.setAttribute("src", state.art);
    } else {
      slots.art.removeAttribute("src");
    }
  }
}

function reloadStylesheets(rev) {
  document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
    const url = new URL(link.getAttribute("href"), location.href);
    url.searchParams.set("v", String(rev));
    link.setAttribute("href", url.pathname + url.search);
  });
}

function applyState(state, force) {
  if (state.power) {
    root.dataset.power = "yes";
  } else {
    delete root.dataset.power;
  }
  if (state.assets_rev === undefined) {
    delete root.dataset.dev;
  } else {
    root.dataset.dev = "yes";
    if (assetsRev !== null && state.assets_rev !== assetsRev) {
      reloadStylesheets(state.assets_rev);
    }
    assetsRev = state.assets_rev;
  }
  if (!force && state.rev === lastRev) {
    return;
  }
  lastRev = state.rev;
  render(state);
}

async function poll(force) {
  const path = scenario ? `/api/state?mock=${encodeURIComponent(scenario)}` : "/api/state";
  let response;
  try {
    response = await fetch(path, { cache: "no-store" });
  } catch (e) {
    return;
  }
  if (!response.ok) {
    return;
  }
  applyState(await response.json(), force);
}

async function send(action, value) {
  const body = value === undefined ? { action } : { action, value };
  let response;
  try {
    response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    return;
  }
  if (response.ok) {
    applyState(await response.json(), true);
  }
}

// サーバの応答を待たずに見た目を先に動かす。応答が届いたら上書きされる
function optimistic(changes) {
  if (current) {
    render({ ...current, ...changes });
  }
}

// 連打しても WiiM へは最後の値だけを絶対値で送る
function changeVolume(delta) {
  const base = pendingVolume !== null ? pendingVolume : current ? current.vol : 0;
  const value = Math.min(100, Math.max(0, base + delta));
  if (value === base) {
    return;
  }
  optimistic({ vol: value });
  pendingVolume = value;
  if (volumeTimer === null) {
    volumeTimer = setTimeout(flushVolume, VOLUME_THROTTLE);
  }
}

function flushVolume() {
  volumeTimer = null;
  const value = pendingVolume;
  pendingVolume = null;
  if (value !== null) {
    send("vol", value);
  }
}

async function loadDiag() {
  let response;
  try {
    response = await fetch("/api/diag", { cache: "no-store" });
  } catch (e) {
    return;
  }
  if (!response.ok) {
    return;
  }
  const info = await response.json();

  if (info.throttle) {
    root.dataset.throttle = info.throttle;
  } else {
    delete root.dataset.throttle;
  }
  setText("diag-host", info.hostname);
  setText("diag-ip", info.ip || "-");
  setText("diag-throttle", info.throttle_raw || "");
  setText("diag-temp", info.temp_c === null ? "-" : `${info.temp_c} °C`);
  setText(
    "diag-mem",
    info.mem_total_mb === null ? "-" : `${info.mem_available_mb} / ${info.mem_total_mb} MB`,
  );
}

// 実行を受け付けたらサーバは停止に向かうため、ポーリングを止めて画面を固定する
async function sendPower(action) {
  root.dataset.dialog = action;
  let response;
  try {
    response = await fetch("/api/power", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
  } catch (e) {
    delete root.dataset.dialog;
    return;
  }
  if (!response.ok) {
    delete root.dataset.dialog;
    return;
  }
  clearInterval(pollTimer);
}

const handlers = {
  prev: () => send("prev"),
  next: () => send("next"),
  "vol-up": () => changeVolume(VOLUME_STEP),
  "vol-down": () => changeVolume(-VOLUME_STEP),
  playpause: () => {
    const playing = current && current.status === "play";
    optimistic({ status: playing ? "pause" : "play" });
    send(playing ? "pause" : "play");
  },
  mute: () => {
    const muted = !(current && current.muted);
    optimistic({ muted });
    send("mute", muted);
  },
  "power-open": () => {
    root.dataset.dialog = "power";
    loadDiag();
  },
  "power-cancel": () => {
    delete root.dataset.dialog;
  },
  "power-off": () => sendPower("poweroff"),
  "power-reboot": () => sendPower("reboot"),
};

document.querySelectorAll("[data-action]").forEach((el) => {
  el.addEventListener("click", handlers[el.dataset.action]);
});

// 消灯からの復帰をサーバへ伝える。タッチはブラウザにしか届かないため、ここで中継する
document.addEventListener("pointerdown", () => {
  const now = Date.now();
  if (now - lastWake < WAKE_THROTTLE) {
    return;
  }
  lastWake = now;
  fetch("/api/wake", { method: "POST" })
    .then((response) => (response.ok ? response.json() : null))
    .then((state) => state && applyState(state, true))
    .catch(() => {});
});

document.querySelectorAll("[data-mock]").forEach((el) => {
  el.addEventListener("click", () => {
    scenario = el.dataset.mock;
    poll(true);
  });
});

if (new URLSearchParams(location.search).has("frame")) {
  root.dataset.frame = "yes";
}

poll(true);
pollTimer = setInterval(poll, POLL_INTERVAL);
