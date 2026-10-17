const $ = (id) => document.getElementById(id);
const DEFAULTS = { backendUrl: "http://127.0.0.1:8765", token: "", minSeconds: 20, blocked: [] };

chrome.storage.sync.get(Object.keys(DEFAULTS), (v) => {
  const s = Object.assign({}, DEFAULTS, v);
  $("token").value = s.token;
  $("backendUrl").value = s.backendUrl;
  $("minSeconds").value = s.minSeconds;
  $("blocked").value = (s.blocked || []).join("\n");
});

$("save").onclick = () => {
  chrome.storage.sync.set({
    token: $("token").value.trim(),
    backendUrl: $("backendUrl").value.trim().replace(/\/$/, "") || DEFAULTS.backendUrl,
    minSeconds: Math.max(5, parseInt($("minSeconds").value, 10) || 20),
    blocked: $("blocked").value.split(/\s+/).map((h) => h.trim()).filter(Boolean),
  }, () => { $("saved").textContent = "Saved"; setTimeout(() => ($("saved").textContent = ""), 1500); });
};
