// Runs on every page. On a page with readable text it guarantees a Michael card: at the reading time (20 s by
// default) the card always appears - with the matching topic if Michael has answered, otherwise as "Matching…"
// that fills in when the answer arrives - and by DEADLINE it is final: if Michael still hasn't answered (busy or
// offline) it says so and offers Retry / Save for later instead of silently showing nothing.
(() => {
  if (window.top !== window || window.__michaelLoaded) return;
  window.__michaelLoaded = true;

  // never on mail, banking, social media, search, shopping, video or local pages
  const NEVER = /(^|\.)(mail\.google|outlook\.|google\.[a-z.]+$|bing\.com|duckduckgo\.com|facebook\.com|instagram\.com|x\.com|twitter\.com|linkedin\.com|reddit\.com|youtube\.com|netflix\.com|amazon\.|flipkart\.com|whatsapp\.com|web\.telegram|paypal\.com|bank|localhost$|127\.0\.0\.1$)/i;
  const MIN_WORDS = 120;          // below this the page has no readable text to match (an app, a login page...)
  const GRACE_MS = 5000;          // card shown at the reading time; final (answer, or "busy") at most 5 s later

  const send = (msg) => new Promise((resolve) => chrome.runtime.sendMessage(msg, (r) => resolve(r || { ok: false })));

  // textContent, not innerText: innerText forces a layout of the whole page, which is slow on long articles.
  // Stops once there is enough text to classify (the backend reads 3,000 characters).
  function articleText() {
    const root = document.querySelector("article, main, [role=main]") || document.body;
    const out = [];
    let words = 0;
    for (const p of root.querySelectorAll("p, li, td, pre, h1, h2, h3")) {
      const t = p.textContent.replace(/\s+/g, " ").trim();
      if (t.length <= 25) continue;
      out.push(t);
      words += t.split(" ").length;
      if (words > 1200) break;
    }
    return out.join("\n");
  }

  // one lookup per page, shared by the early prefetch, the timed card and the scroll trigger
  let page = { url: "", shown: false, timer: 0, lookup: null, result: null, text: "" };

  function lookup() {
    if (!page.lookup) {
      const url = page.url;
      page.lookup = send({ type: "classify", url: location.href, title: document.title, text: page.text.slice(0, 3000) })
        .then((r) => { if (url === page.url) page.result = r; return r; });
    }
    return page.lookup;
  }

  async function showWhenReady(force = false) {
    if (page.shown && !force) return;
    page.shown = true;
    if (force) { page.text = articleText() || document.title; page.lookup = null; page.result = null; }
    const url = page.url;
    const card = makeCard();
    if (page.result?.ok) return fill(card, page.result, force);
    card.pending();                                   // the card is up now - the answer fills it in
    const r = await Promise.race([lookup(), new Promise((res) => setTimeout(() => res(null), GRACE_MS))]);
    if (url !== page.url || !card.alive()) return;
    if (r && r.ok) fill(card, r, force);
    else card.busy(r && r.error === "token" ? "token" : "busy");
  }

  async function watch() {
    const url = location.href.split("#")[0];
    if (url === page.url) return;
    clearTimeout(page.timer);
    document.getElementById("michael-card")?.remove();
    page = { url, shown: false, timer: 0, lookup: null, result: null, text: "" };
    if (NEVER.test(location.hostname)) return;
    const res = await send({ type: "settings" });
    if (!res.ok) return;
    const s = res.settings;
    if (s.paused || (s.blocked || []).includes(location.hostname)) return;
    if ((await chrome.storage.local.get(`michael:seen:${url}`))[`michael:seen:${url}`]) {   // you acted on it before:
      page.shown = true;                                                                   // stay quiet, but keep
      send({ type: "classify", url: location.href, title: document.title, text: "" });     // the ✓ badge right
      return;
    }
    setTimeout(() => {                                // let the page render its text, then start matching early
      if (url !== page.url) return;
      page.text = articleText();
      if (page.text.split(/\s+/).length < MIN_WORDS) { page.shown = true; return; }   // nothing readable to match
      lookup();
    }, 2000);
    page.timer = setTimeout(() => {
      if (url !== page.url || page.shown) return;
      if (!page.text) page.text = articleText();      // a short reading time can come before the early read
      if (page.text.split(/\s+/).length >= MIN_WORDS) showWhenReady();
    }, (s.minSeconds || 20) * 1000);
  }

  function main() {
    watch();
    setInterval(watch, 1500);                       // URL changes on single-page sites (cheap string compare)
    addEventListener("scroll", () => {               // clearly reading (30% down, 8 s in): no need to wait 20 s
      if (page.shown || !page.text) return;
      const seen = (scrollY + innerHeight) / Math.max(document.body.scrollHeight, 1);
      if (seen > 0.3 && page.result?.ok) showWhenReady();
    }, { passive: true });
    chrome.runtime.onMessage.addListener((msg) => {   // Alt+Shift+M / the right-click menu, via the background worker
      if (msg.type === "now") showWhenReady(true);
      if (msg.type === "check") factCheck(msg.text);
    });
  }

  const remember = () => chrome.storage.local.set({ [`michael:seen:${page.url}`]: Date.now() });

  // ------------------------------------------------------------------ the card (shadow DOM: page CSS can't touch it)
  function makeCard() {
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
        .dots::after{content:"";animation:d 1.2s steps(4) infinite} @keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
      </style>
      <div class="card"><div class="t"><span>Michael</span><span class="x" title="Close">✕</span></div><div class="body"></div></div>`;
    document.documentElement.appendChild(host);
    const body = root.querySelector(".body");
    let timer = 0;
    const close = () => { clearTimeout(timer); host.remove(); };
    const autoHide = (ms) => { clearTimeout(timer); timer = setTimeout(close, ms); };
    root.querySelector(".x").onclick = () => { remember(); close(); };
    host.addEventListener("mouseenter", () => clearTimeout(timer));
    return {
      host, body, close, autoHide,
      alive: () => host.isConnected,
      pending() { body.innerHTML = `<span class="dots">Matching this page to your library</span>`; },
      busy(kind) {
        body.innerHTML = kind === "token"
          ? `<span class="muted">The extension isn't connected: open its Settings and paste the token from Obsidian ("Michael: Copy extension token").</span>`
          : `<div>Michael didn't answer in time (busy or offline).</div>
             <div class="row"><button class="primary retry">Retry</button><button class="later">Save for later</button></div>`;
        body.querySelector(".retry")?.addEventListener("click", () => { close(); page.shown = false; page.lookup = null; showWhenReady(); });
        body.querySelector(".later")?.addEventListener("click", async () => {
          await send({ type: "queue", url: location.href, title: document.title, text: page.text.slice(0, 3000) });
          remember();
          body.innerHTML = `<span class="muted">Saved - Michael files it into the right topic as soon as it's back.</span>`;
          autoHide(4000);
        });
        autoHide(20000);
      },
    };
  }

  function fill(card, r, force) {
    const { body, close, autoHide } = card;
    autoHide(15000);
    if (r.already_saved) {
      body.innerHTML = `✓ Already in your library: <span class="topic"></span>`;
      body.querySelector(".topic").textContent = `${r.already_saved.subject} › ${r.already_saved.title}`;
      remember();
      knownFacts(card);
      return;
    }
    const best = (r.suggestions || [])[0];
    if (!best) { card.busy("busy"); return; }
    const low = r.inbox || !r.relevant;              // no clear topic: offer the subject's Inbox
    let choice = { subject: best.subject, topic: low ? "Inbox" : best.topic };

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
      ? "Not a clear match for any of your topics, so it would go to the Inbox."
      : `${Math.round(best.match * 100)}% match` + ((r.suggestions || [])[1] ? ` · next: ${r.suggestions[1].topic}` : "");

    body.querySelector(".add").onclick = async () => {
      const a = await send({ type: "add", url: location.href, title: document.title, ...choice });
      remember();
      body.innerHTML = a.ok ? `Added to <span class="topic"></span>.` : `<span class="muted">Michael is offline - start it from Obsidian.</span>`;
      if (a.ok) label();
      autoHide(4000);
    };
    body.querySelector(".later").onclick = () => { remember(); close(); };
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
    knownFacts(card);
  }

  // Facts Michael has already verified on this page's subject, appended once the card is up (never delays it).
  async function knownFacts(card) {
    const q = document.title.replace(/\s[-|–—:]\s(?!.*\s[-|–—:]\s).*$/, "").trim();   // "Euclidean algorithm - Wikipedia"
    if (!q) return;
    const r = await Promise.race([send({ type: "facts", q }), new Promise((ok) => setTimeout(() => ok(null), 4000))]);
    if (!r?.ok || !r.facts.length || !card.alive()) return;
    const box = document.createElement("details");
    box.style.cssText = "margin-top:10px;border-top:1px solid #3b3b55;padding-top:6px";
    box.innerHTML = `<summary class="muted" style="cursor:pointer"></summary>`;
    box.querySelector("summary").textContent = `You already have ${r.facts.length} verified fact${r.facts.length > 1 ? "s" : ""} on this`;
    for (const f of r.facts) {
      const row = document.createElement("div");
      row.style.cssText = "border-left:3px solid #7ee2a8;padding:3px 8px;margin:6px 0";
      row.textContent = `✓ ${f.fact}`;
      const src = document.createElement("div");
      src.className = "muted";
      src.textContent = (f.source || "").replace(/^\[\[|\]\]$/g, "");
      row.append(src);
      box.append(row);
    }
    card.body.append(box);
  }

  // ------------------------------------------------------------------ fact-check a selection against the library
  async function factCheck(text) {
    page.shown = true;                                // the automatic topic card must not replace a check you asked for
    const card = makeCard();
    card.body.innerHTML = `<span class="dots">Checking each sentence against your library</span>`;
    const r = await send({ type: "check", text });
    if (!card.alive()) return;
    if (!r.ok) { card.busy(r.error === "token" ? "token" : "busy"); return; }
    const icon = { SUPPORTED: "✓", PARTIAL: "◐", UNSUPPORTED: "✗" };
    const colour = { SUPPORTED: "#7ee2a8", PARTIAL: "#f5d36b", UNSUPPORTED: "#ff8a8a" };
    const s = r.summary;
    card.body.innerHTML = `<div class="muted">✓ ${s.supported} supported · ◐ ${s.partial} partial · ✗ ${s.unsupported} not found in your library</div>
      <div class="list" style="max-height:340px;overflow:auto;margin-top:6px"></div>`;
    const list = card.body.querySelector(".list");
    for (const c of r.sentences) {
      const row = document.createElement("div");
      row.style.cssText = `border-left:3px solid ${colour[c.verdict]};padding:4px 8px;margin:6px 0`;
      const head = document.createElement("div");
      head.textContent = `${icon[c.verdict]} ${c.sentence}`;
      row.append(head);
      if (c.verdict !== "UNSUPPORTED" && c.quote) {
        const q = document.createElement("div");
        q.className = "muted";
        q.textContent = `“${c.quote.slice(0, 260)}${c.quote.length > 260 ? "…" : ""}” — ${c.source.replace(/^\[\[|\]\]$/g, "")}`;
        row.append(q);
      }
      list.append(row);
    }
    card.autoHide(60000);
  }

  main();
})();
