// Runs on every page but stays silent unless the page is an article you have actually been reading.
// Then it asks Michael (locally) which library topic the page belongs to and offers to add its link there.
(() => {
  if (window.top !== window || window.__michaelLoaded) return;
  window.__michaelLoaded = true;

  // never on mail, banking, social media, search, shopping, video or local pages
  const NEVER = /(^|\.)(mail\.google|outlook\.|google\.[a-z.]+$|bing\.com|duckduckgo\.com|facebook\.com|instagram\.com|x\.com|twitter\.com|linkedin\.com|reddit\.com|youtube\.com|netflix\.com|amazon\.|flipkart\.com|whatsapp\.com|web\.telegram|paypal\.com|bank|localhost$|127\.0\.0\.1$)/i;

  const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false })));

  // textContent, not innerText: innerText forces a layout of the whole page, which is slow on long articles.
  // Stops once there is enough text to decide and classify (the backend reads 3,000 characters).
  function articleText() {
    const root = document.querySelector("article, main, [role=main]") || document.body;
    const out = [];
    let words = 0;
    for (const p of root.querySelectorAll("p, li")) {
      const t = p.textContent.replace(/\s+/g, " ").trim();
      if (t.length <= 40) continue;
      out.push(t);
      words += t.split(" ").length;
      if (words > 1200) break;
    }
    return out.join("\n");
  }

  function looksLikeArticle(text) {
    const og = document.querySelector('meta[property="og:type"]')?.content || "";
    const words = text.split(/\s+/).length;
    return (document.querySelector("article") || og === "article") ? words > 250 : words > 600;
  }

  // state for the page being read; single-page sites change the URL without reloading, so it is reset per URL
  let page = { url: "", fired: false, since: 0, timer: 0, prefetch: 0, text: null, article: null };

  // read the page once per URL (the scroll handler would otherwise re-read it on every scroll event)
  function pageText() {
    if (page.text === null) {
      page.text = articleText();
      page.article = looksLikeArticle(page.text);
    }
    return page.text;
  }

  // classify in the background a few seconds after load: by the time the reading time is up the answer is
  // already cached in the extension, so the card appears instantly instead of after a backend round trip
  function prefetch() {
    const text = pageText();
    if (!page.fired && page.article)
      send({ type: "classify", url: location.href, title: document.title, text: text.slice(0, 3000) });
  }

  async function ask(force = false) {
    if (page.fired && !force) return;
    const text = force ? articleText() : pageText();
    if (!force && !page.article) return;
    page.fired = true;
    const key = `michael:seen:${page.url}`;
    await chrome.storage.local.set({ [key]: Date.now() });
    const r = await send({ type: "classify", url: location.href, title: document.title, text: text.slice(0, 3000) || document.title });
    if (r.ok) showToast(r, force);
    else if (force) showToast({ offline: true }, true);
  }

  async function watch() {
    const url = location.href.split("#")[0];
    if (url === page.url) return;
    clearTimeout(page.timer);
    clearTimeout(page.prefetch);
    page = { url, fired: false, since: performance.now(), timer: 0, prefetch: 0, text: null, article: null };
    const host = location.hostname;
    if (NEVER.test(host)) return;
    const res = await send({ type: "settings" });
    if (!res.ok) return;
    const s = res.settings;
    if (s.paused || !s.token || (s.blocked || []).includes(host)) return;
    if ((await chrome.storage.local.get(`michael:seen:${url}`))[`michael:seen:${url}`]) {   // asked before:
      page.fired = true;                                                                   // stay quiet, but
      send({ type: "classify", url: location.href, title: document.title, text: "" });     // keep the ✓ badge right
      return;
    }
    page.prefetch = setTimeout(prefetch, 3000);
    page.timer = setTimeout(() => ask(), (s.minSeconds || 20) * 1000);
  }

  function main() {
    watch();
    setInterval(watch, 1500);                       // URL changes on single-page sites (cheap string compare)
    addEventListener("scroll", () => {
      if (page.fired || page.article === false) return;
      const seen = (scrollY + innerHeight) / Math.max(document.body.scrollHeight, 1);
      if (seen > 0.3 && performance.now() - page.since > 8000) ask();
    }, { passive: true });
    chrome.runtime.onMessage.addListener((msg) => {   // Alt+Shift+M from the background worker
      if (msg.type === "now") ask(true);
    });
  }

  // ------------------------------------------------------------------ the pop-up (shadow DOM: page CSS can't touch it)
  function showToast(r, force = false) {
    // unrelated page: no card at all - unless you asked for it with the shortcut
    if (!force && !r.already_saved && (!r.relevant || !(r.suggestions || [])[0])) return;
    document.getElementById("michael-card")?.remove();
    const host = document.createElement("div");
    host.id = "michael-card";
    host.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483647";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        .card{font:13px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:#1e1e2e;color:#e6e6f0;border:1px solid #3b3b55;
              border-radius:12px;padding:12px 14px;width:320px;box-shadow:0 8px 28px rgba(0,0,0,.35)}
        .t{font-weight:600;margin-bottom:6px;display:flex;justify-content:space-between}
        .x{cursor:pointer;opacity:.6} .x:hover{opacity:1}
        .topic{color:#c9b6ff;font-weight:600} .muted{opacity:.7;font-size:12px}
        .row{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
        button{font:inherit;border-radius:8px;border:1px solid #4a4a6a;background:#2a2a40;color:#e6e6f0;padding:5px 10px;cursor:pointer}
        button.primary{background:#7c5cff;border-color:#7c5cff;color:white}
        select{font:inherit;width:100%;margin-top:8px;background:#2a2a40;color:#e6e6f0;border:1px solid #4a4a6a;border-radius:8px;padding:4px}
      </style>
      <div class="card"><div class="t"><span>Michael</span><span class="x" title="Close">✕</span></div><div class="body"></div></div>`;
    document.documentElement.appendChild(host);
    const body = root.querySelector(".body");
    const close = () => host.remove();
    root.querySelector(".x").onclick = close;
    let timer = setTimeout(close, 15000);
    host.addEventListener("mouseenter", () => clearTimeout(timer));

    if (r.offline) {
      body.innerHTML = `<span class="muted">Michael is offline - open Obsidian (the plugin starts it).</span>`;
      return;
    }
    if (r.already_saved) {
      body.innerHTML = `Already in your library: <span class="topic"></span>`;
      body.querySelector(".topic").textContent = `${r.already_saved.subject} › ${r.already_saved.title}`;
      return;
    }
    const best = (r.suggestions || [])[0];
    if (!best) { host.remove(); return; }
    const low = r.inbox || !r.relevant;        // shortcut on an unrelated page: offer the Inbox
    let choice = best ? { subject: best.subject, topic: low ? "Inbox" : best.topic } : null;
    if (!choice) { close(); return; }

    body.innerHTML = `
      <div>Add this page to <span class="topic"></span>?</div>
      <div class="muted conf"></div>
      <select style="display:none"></select>
      <div class="row">
        <button class="primary add">Add</button><button class="other">Other topic</button>
        <button class="later">Not now</button><button class="never">Never on this site</button>
      </div>`;
    const label = () => (body.querySelector(".topic").textContent = `${choice.subject} › ${choice.topic}`);
    label();
    body.querySelector(".conf").textContent = low
      ? "Not a clear match for any topic, so it goes to the Inbox."
      : `${Math.round(best.match * 100)}% match` +
        ((r.suggestions || [])[1] ? ` · next: ${r.suggestions[1].topic}` : "");

    body.querySelector(".add").onclick = async () => {
      const a = await send({ type: "add", url: location.href, title: document.title, ...choice });
      body.innerHTML = a.ok ? `Added to <span class="topic"></span>.` : `<span class="muted">Michael is offline - start it from Obsidian.</span>`;
      if (a.ok) label();
      clearTimeout(timer); timer = setTimeout(close, 4000);
    };
    body.querySelector(".later").onclick = close;
    body.querySelector(".never").onclick = async () => { await send({ type: "block", host: location.hostname }); close(); };
    body.querySelector(".other").onclick = async () => {
      const sel = body.querySelector("select");
      const t = await send({ type: "topics" });
      if (!t.ok) return;
      sel.innerHTML = t.topics.map((s) => `<optgroup label="${s.subject}">` +
        s.topics.map((x) => `<option value="${s.subject}|||${x}">${x}</option>`).join("") + "</optgroup>").join("");
      sel.value = `${choice.subject}|||${choice.topic}`;
      sel.style.display = "block";
      sel.onchange = () => { const [subject, topic] = sel.value.split("|||"); choice = { subject, topic }; label(); };
    };
  }

  main();
})();
