// Talks to the local Michael backend for the content script and the toolbar pop-up.
// Only http://127.0.0.1 is contacted; page text never leaves the computer.

const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8765",
  token: "",
  minSeconds: 20,
  paused: false,
  blocked: [],          // hostnames where the pop-up never appears ("Never on this site")
};

// settings are read on every message: keep them in memory and drop the copy when they change
let cachedSettings = null;
chrome.storage.onChanged.addListener((_, area) => { if (area === "sync") cachedSettings = null; });

async function settings() {
  if (cachedSettings) return cachedSettings;
  const s = Object.assign({}, DEFAULTS, await chrome.storage.sync.get(Object.keys(DEFAULTS)));
  if (!s.token) {
    // the backend writes local-token.json into this unpacked extension folder: connect without copy-paste
    try {
      const t = (await (await fetch(chrome.runtime.getURL("local-token.json"))).json()).token;
      if (t) { s.token = t; await chrome.storage.sync.set({ token: t }); }
    } catch (e) { /* not there yet: the user can paste the token in Settings */ }
  }
  return (cachedSettings = s);
}

async function api(path, body) {
  const s = await settings();
  const res = await fetch(`${s.backendUrl}${path}`, {
    signal: AbortSignal.timeout(15000),               // a stuck backend must not hold the card forever
    method: body ? "POST" : "GET",
    headers: { "content-type": "application/json", "X-Michael-Token": s.token },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new Error("token");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// one classification per page per browser session: the card and the toolbar pop-up share it
const pageKey = (url) => `cls:${url.split("#")[0]}`;

const inFlight = new Map();     // a prefetch still running: the card waits for it instead of asking twice

async function classify(url, title, text) {
  const key = pageKey(url);
  const hit = (await chrome.storage.session.get(key))[key];
  if (hit) return hit;
  if (!text && !inFlight.has(key)) return api("/api/v1/classify", { url, title, text });   // badge check only
  if (!inFlight.has(key)) {
    inFlight.set(key, classifyWithRetry(url, title, text)
      .then(async (r) => { await chrome.storage.session.set({ [key]: r }); flushQueue(); return r; })
      .finally(() => inFlight.delete(key)));
  }
  return inFlight.get(key);
}

// one quick retry: a lookup that fails fast (backend restarting, connection refused) gets a second chance well
// inside the card's 20-25 s window; a lookup that times out (15 s) is not retried - the card reports "busy"
async function classifyWithRetry(url, title, text) {
  const started = Date.now();
  try {
    return await api("/api/v1/classify", { url, title, text });
  } catch (e) {
    if (e.message === "token" || Date.now() - started > 5000) throw e;
    await new Promise((r) => setTimeout(r, 2000));
    return api("/api/v1/classify", { url, title, text });
  }
}

// "Save for later" while Michael is busy or offline: kept here and filed (best topic, or the subject's Inbox) as soon
// as Michael answers any lookup again
async function queuePage(url, title, text) {
  const q = (await chrome.storage.local.get("michael:queue"))["michael:queue"] || [];
  if (!q.some((p) => p.url === url)) q.push({ url, title, text, at: Date.now() });
  await chrome.storage.local.set({ "michael:queue": q });
}

let flushing = false;
async function flushQueue() {
  if (flushing) return;
  flushing = true;
  try {
    const q = (await chrome.storage.local.get("michael:queue"))["michael:queue"] || [];
    const left = [];
    for (const p of q) {
      try {
        const r = await api("/api/v1/classify", { url: p.url, title: p.title, text: p.text });
        const best = (r.suggestions || [])[0];
        if (!r.already_saved && best)
          await api("/api/v1/links", { url: p.url, title: p.title, subject: best.subject,
                                       topic: r.relevant && !r.inbox ? best.topic : "Inbox" });
      } catch (e) {
        left.push(p);                                   // still unreachable: keep it for next time
      }
    }
    await chrome.storage.local.set({ "michael:queue": left });
  } finally {
    flushing = false;
  }
}

async function markSaved(tabId, saved) {
  if (tabId == null) return;
  await chrome.action.setBadgeText({ tabId, text: saved ? "✓" : "" });
  if (saved) await chrome.action.setBadgeBackgroundColor({ tabId, color: "#36b37e" });
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    const tabId = sender.tab?.id ?? msg.tabId;
    try {
      const s = await settings();
      switch (msg.type) {
        case "settings":
          return reply({ ok: true, settings: s });
        case "classify": {
          const r = await classify(msg.url, msg.title, msg.text);
          await markSaved(tabId, !!r.already_saved);
          return reply({ ok: true, ...r });
        }
        case "add": {
          const r = await api("/api/v1/links", { url: msg.url, title: msg.title, subject: msg.subject, topic: msg.topic });
          await chrome.storage.session.remove(pageKey(msg.url));     // next look-up says "already saved"
          await markSaved(tabId, true);
          return reply({ ok: true, ...r });
        }
        case "topics":
          return reply({ ok: true, topics: await api("/api/v1/topics") });
        case "recent":
          return reply({ ok: true, links: await api("/api/v1/links?limit=5") });
        case "health":
          return reply({ ok: true, ...(await (await fetch(`${s.backendUrl}/health`)).json()) });
        case "check": {                                  // fact-checking can take a minute: no 15 s cap here
          const s2 = await settings();
          const res = await fetch(`${s2.backendUrl}/api/v1/check`, {
            method: "POST", signal: AbortSignal.timeout(180000),
            headers: { "content-type": "application/json", "X-Michael-Token": s2.token },
            body: JSON.stringify({ text: msg.text }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return reply({ ok: true, ...(await res.json()) });
        }
        case "queue":
          await queuePage(msg.url, msg.title, msg.text);
          return reply({ ok: true });
        case "block": {
          const blocked = Array.from(new Set([...(s.blocked || []), msg.host]));
          await chrome.storage.sync.set({ blocked });
          return reply({ ok: true });
        }
        default:
          return reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      reply({ ok: false, error: e.message === "token" ? "token" : "offline" });
    }
  })();
  return true;    // keep the channel open for the async reply
});

// Alt+Shift+M: ask about this page right now (no waiting, even if it was dismissed before)
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "add-page") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id != null) chrome.tabs.sendMessage(tab.id, { type: "now" }).catch(() => {});
});

// 0.2.2: pages were marked "seen" before Michael answered, so lookups that failed while the backend was busy silenced
// those pages for good. Forget every remembered page once on update; from now on only answered lookups are kept.
chrome.runtime.onInstalled.addListener(async () => {
  const all = await chrome.storage.local.get(null);
  const stale = Object.keys(all).filter((k) => k.startsWith("michael:seen:"));
  if (stale.length) await chrome.storage.local.remove(stale);
});

// Right-click a selection -> "Fact-check with Michael": every sentence of the selected text is checked against your
// library's source articles (the same verifier as Michael's notes); the card in the page shows each verdict.
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "michael-check", title: "Fact-check with Michael", contexts: ["selection"] });
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "michael-check" && tab?.id != null)
    chrome.tabs.sendMessage(tab.id, { type: "check", text: info.selectionText || "" }).catch(() => {});
});
