const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false })));
const $ = (id) => document.getElementById(id);

async function init() {
  const s = (await send({ type: "settings" })).settings || {};
  $("pause").textContent = s.paused ? "Resume pop-ups" : "Pause pop-ups";
  const h = await send({ type: "health" });
  if (!h.ok) {
    $("status").innerHTML = '<span class="bad">Offline</span> - open Obsidian (the Michael plugin starts the backend).';
    $("add").disabled = true;
    return;
  }
  if (!s.token) {
    $("status").innerHTML = '<span class="bad">No token</span> - in Obsidian run "Michael: Copy extension token", then paste it in Settings.';
    $("add").disabled = true;
    return;
  }
  $("status").innerHTML = `<span class="ok">Connected</span> · ${h.llm}`;
  const r = await send({ type: "recent" });
  if (r.ok && r.links.length) {
    $("recent").innerHTML = "";
    for (const l of r.links) {
      const li = document.createElement("li");
      li.textContent = `${l.title} → ${l.topic}`;
      $("recent").appendChild(li);
    }
  }
}

$("add").onclick = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $("add").disabled = true;
  $("result").textContent = "Finding the right topic…";
  let text = tab.title;
  try {        // the open page's text (activeTab: only this tab, only when you click)
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => document.body.innerText.slice(0, 3000) });
    text = res.result || text;
  } catch (e) { /* chrome:// pages etc. */ }
  const c = await send({ type: "classify", tabId: tab.id, url: tab.url, title: tab.title, text });
  if (!c.ok) { $("result").textContent = c.error === "token" ? "Wrong token - check Settings." : "Michael is offline."; return; }
  if (c.already_saved) { $("result").textContent = `Already in your library: ${c.already_saved.subject} › ${c.already_saved.title}`; return; }
  const best = c.suggestions[0];
  if (!best) { $("result").textContent = "No library topics yet."; return; }
  const topic = c.inbox ? "Inbox" : best.topic;      // you asked for it, so even unrelated pages can go to an Inbox
  const a = await send({ type: "add", tabId: tab.id, url: tab.url, title: tab.title, subject: best.subject, topic });
  $("result").textContent = a.ok ? `Added to ${best.subject} › ${topic}` : "Could not add - is Michael running?";
  init();
};
$("options").onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };
$("pause").onclick = async (e) => {
  e.preventDefault();
  const s = (await send({ type: "settings" })).settings;
  await chrome.storage.sync.set({ paused: !s.paused });
  init();
};
init();
