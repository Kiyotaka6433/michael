// Talks to the local Michael backend for the content script and the toolbar pop-up.
// Only http://127.0.0.1 is contacted; page text never leaves the computer.

const DEFAULTS = {
  backendUrl: "http://127.0.0.1:8765",
  token: "",
  minSeconds: 20,
  paused: false,
  blocked: [],          // hostnames where the pop-up never appears ("Never on this site")
};

async function settings() {
  const s = Object.assign({}, DEFAULTS, await chrome.storage.sync.get(Object.keys(DEFAULTS)));
  if (!s.token) {
    // the backend writes local-token.json into this unpacked extension folder: connect without copy-paste
    try {
      const t = (await (await fetch(chrome.runtime.getURL("local-token.json"))).json()).token;
      if (t) { s.token = t; await chrome.storage.sync.set({ token: t }); }
    } catch (e) { /* not there yet: the user can paste the token in Settings */ }
  }
  return s;
}

async function api(path, body) {
  const s = await settings();
  const res = await fetch(`${s.backendUrl}${path}`, {
    method: body ? "POST" : "GET",
    headers: { "content-type": "application/json", "X-Michael-Token": s.token },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) throw new Error("token");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      const s = await settings();
      switch (msg.type) {
        case "settings":
          return reply({ ok: true, settings: s });
        case "classify":
          return reply({ ok: true, ...(await api("/api/v1/classify", { url: msg.url, title: msg.title, text: msg.text })) });
        case "add":
          return reply({ ok: true, ...(await api("/api/v1/links", { url: msg.url, title: msg.title, subject: msg.subject, topic: msg.topic })) });
        case "topics":
          return reply({ ok: true, topics: await api("/api/v1/topics") });
        case "recent":
          return reply({ ok: true, links: await api("/api/v1/links?limit=5") });
        case "health":
          return reply({ ok: true, ...(await (await fetch(`${s.backendUrl}/health`)).json()) });
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
