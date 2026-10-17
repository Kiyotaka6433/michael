// Runs on every page but stays silent unless the page is an article you have actually been reading.
// Then it asks Michael (locally) which library topic the page belongs to and offers to add its link there.
(() => {
  if (window.top !== window || window.__michaelLoaded) return;
  window.__michaelLoaded = true;

  // never on mail, banking, social media, search, shopping, video or local pages
  const NEVER = /(^|\.)(mail\.google|outlook\.|google\.[a-z.]+$|bing\.com|duckduckgo\.com|facebook\.com|instagram\.com|x\.com|twitter\.com|linkedin\.com|reddit\.com|youtube\.com|netflix\.com|amazon\.|flipkart\.com|whatsapp\.com|web\.telegram|paypal\.com|bank|localhost$|127\.0\.0\.1$)/i;

  const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false })));

  function articleText() {
    const root = document.querySelector("article, main, [role=main]") || document.body;
    const paras = Array.from(root.querySelectorAll("p, li")).map((p) => p.innerText.trim()).filter((t) => t.length > 40);
    return paras.join("\n");
  }

  function looksLikeArticle(text) {
    const og = document.querySelector('meta[property="og:type"]')?.content || "";
    const words = text.split(/\s+/).length;
    return (document.querySelector("article") || og === "article") ? words > 250 : words > 600;
  }

  async function main() {
    const host = location.hostname;
    if (NEVER.test(host)) return;
    const res = await send({ type: "settings" });
    if (!res.ok) return;
    const s = res.settings;
    if (s.paused || !s.token || (s.blocked || []).includes(host)) return;
    const key = `michael:seen:${location.href.split("#")[0]}`;
    if ((await chrome.storage.local.get(key))[key]) return;      // asked about this page before

    let fired = false;
    const fire = async () => {
      if (fired) return;
      const text = articleText();
      if (!looksLikeArticle(text)) return;
      fired = true;
      await chrome.storage.local.set({ [key]: Date.now() });
      const r = await send({ type: "classify", url: location.href, title: document.title, text: text.slice(0, 3000) });
      if (r.ok) showToast(r);
    };
    setTimeout(fire, (s.minSeconds || 20) * 1000);
    addEventListener("scroll", () => {
      const seen = (scrollY + innerHeight) / Math.max(document.body.scrollHeight, 1);
      if (seen > 0.3 && performance.now() > 8000) fire();
    }, { passive: true });
  }

  // ------------------------------------------------------------------ the pop-up (shadow DOM: page CSS can't touch it)
  function showToast(r) {
    const host = document.createElement("div");
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

    if (r.already_saved) {
      body.innerHTML = `Already in your library: <span class="topic"></span>`;
      body.querySelector(".topic").textContent = `${r.already_saved.subject} › ${r.already_saved.title}`;
      return;
    }
    const best = (r.suggestions || [])[0];
    const low = !best || best.confidence < (r.inbox_threshold || 0.35);
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
      : `${Math.round(best.confidence * 100)}% match` +
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
