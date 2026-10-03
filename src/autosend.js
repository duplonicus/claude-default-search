// Claude as Default Search, v3.4.
// Address-bar searches carry a secret token. Links from anywhere else don't,
// so Claude's normal "use caution" stop still applies to them.
// The prompts, the model and the project come from defaults.js and the options page.
(() => {
  const TOKEN = "__TOKEN__";
  const USUAL_KEY = "dupsearch-usual-model";
  const MISS_KEY = "dupsearch-project-miss";

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function waitFor(fn, timeout = 15000, every = 50) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(every);
    }
    return null;
  }
  const buttons = () => [...document.querySelectorAll("button")];
  const ariaLabel = (el) => el.getAttribute("aria-label") || "";
  const pickerLabel = () => {
    const b = buttons().find((x) => ariaLabel(x).startsWith("Model:"));
    return b ? ariaLabel(b) : null;
  };
  // "Model: Opus 5.5 Medium" -> "claude-opus-5-5"
  function idFromLabel(l) {
    const m = (l || "").match(/Model:\s*([A-Za-z]+)\s+(\d+(?:\.\d+)?)/);
    return m ? "claude-" + m[1].toLowerCase() + "-" + m[2].replace(/\./g, "-") : null;
  }
  function orgId() {
    const c = document.cookie.split("; ").find((x) => x.startsWith("lastActiveOrg="));
    return c ? decodeURIComponent(c.split("=")[1]) : null;
  }
  const store = {
    get: () => { try { return localStorage.getItem(USUAL_KEY); } catch { return null; } },
    set: (v) => { try { localStorage.setItem(USUAL_KEY, v); } catch {} },
  };
  // The same call claude.ai makes when you change the picker.
  function setAccountModel(id) {
    const org = orgId();
    if (!org || !id) return Promise.resolve(false);
    return fetch("/api/organizations/" + org + "/model_selector_state/chat", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ model: id }),
    }).then((r) => r.ok).catch(() => false);
  }

  // What the options page saved, with defaults.js filling the gaps.
  async function settings() {
    let saved = {};
    try { saved = await chrome.storage.local.get(["preamble", "ask", "summarize", "projectUrl", "model"]); } catch {}
    const pick = (k) => (typeof saved[k] === "string" && saved[k].trim() ? saved[k] : DEFAULTS[k]);
    const project = (String(saved.projectUrl || "").match(PROJECT_ID) || BUILT_PROJECT.match(PROJECT_ID) || [""])[0];
    // The model to switch to, or null to leave your usual model alone.
    const model = saved.model === NO_SWITCH ? null
      : MODELS.find((m) => m.id === saved.model) || MODELS.find((m) => m.id === DEFAULTS.model);
    return { preamble: pick("preamble"), jobs: { ask: pick("ask"), summarize: pick("summarize") }, project, model };
  }

  const promptBox = () =>
    [...document.querySelectorAll('[aria-label="Write your prompt to Claude"]')]
      .find((e) => e.offsetParent !== null);
  // Types the prompt into the box the way a keyboard or a paste would, so the
  // page's editor registers it. Returns the box once the text has stuck.
  const typed = [];
  async function typePrompt(text, timeout = 10000) {
    // One paragraph per line; an empty line stays as an empty paragraph. Runs of
    // spaces are collapsed, because the editor would turn them into other characters.
    const lines = text.replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").split("\n")
      .map((l) => l.replace(/\s+/g, " "));
    const marks = lines.map((l) => l.trim().slice(0, 40)).filter(Boolean);
    const has = (b) => {
      if (!b) return false;
      const shown = b.innerText.replace(/\s+/g, " ");
      return marks.every((m) => shown.includes(m));
    };
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const box = promptBox();
      if (box && !has(box)) {
        box.focus();
        if (box.contains(document.activeElement)) {
          document.execCommand("selectAll");
          lines.forEach((l, i) => {
            if (i) document.execCommand("insertParagraph");
            if (l) document.execCommand("insertText", false, l);
          });
          typed.push("insertText");
        }
        if (!has(box)) {
          const data = new DataTransfer();
          data.setData("text/plain", text);
          box.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true, cancelable: true }));
          typed.push("paste");
        }
      }
      // The page can wipe the box while it finishes loading; make sure it held.
      await sleep(250);
      if (has(promptBox())) return promptBox();
    }
    return null;
  }

  // Switches the account to the search model, sends whatever getBox() puts in
  // the prompt, then puts your usual model back once the chat exists. With no
  // search model, it just sends.
  const ABORT = {};
  async function sendOn(model, getBox, onSent) {
    const usual = store.get() || "claude-opus-5-5";
    if (model) await setAccountModel(model.id);
    const box = await getBox();
    if (box === ABORT) return;
    const send = box && await waitFor(() =>
      buttons().find((b) => ariaLabel(b) === "Send message" && !b.disabled)
    );

    // Fallback: if the page still came up on another model, use the picker.
    if (send && model && !(pickerLabel() || "").includes(model.name)) {
      const p = buttons().find((x) => ariaLabel(x).startsWith("Model:"));
      if (p) {
        p.click();
        const item = await waitFor(() =>
          [...document.querySelectorAll('[role="menuitemradio"]')]
            .find((m) => m.textContent.includes(model.name)), 2000);
        if (item) item.click();
        await waitFor(() => (pickerLabel() || "").includes(model.name), 2000);
      }
    }
    if (send) { send.click(); if (onSent) onSent(); }
    if (!model) return;

    await waitFor(() => location.pathname.startsWith("/chat/"), 8000, 100);
    await sleep(1000);
    await setAccountModel(usual);
  }

  const url = new URL(location.href);
  const jobId = url.searchParams.get("dupjob");
  const isSearch = url.searchParams.get("dupsearch") === TOKEN;

  // Normal visits: just note which model you usually use, so searches can put it back.
  // A page showing the search model may be mid-search, so that one isn't noted.
  if (!jobId && !isSearch) {
    Promise.all([settings(), waitFor(pickerLabel, 15000, 250)]).then(([cfg, l]) => {
      const id = idFromLabel(l);
      if (id && !(cfg.model && l.includes(cfg.model.name))) store.set(id);
    });
    return;
  }

  const link = (path, params) => {
    const u = new URL(path, location.origin);
    for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
    return u.href;
  };
  const onProject = location.pathname.startsWith("/project/");
  // A project page doesn't fill the prompt from the URL, so type it there. If
  // that fails, note what was on the page and carry on from /new instead.
  async function typeOnProject(text, fallback) {
    const box = await typePrompt(text);
    if (box) return box;
    const seen = [...document.querySelectorAll('[contenteditable="true"], textarea')]
      .map((e) => (ariaLabel(e) || e.tagName) + ((e.innerText || e.value || "").trim() ? " (filled)" : " (empty)"));
    try { localStorage.setItem(MISS_KEY, new Date().toISOString() + " tried: " + ([...new Set(typed)].join(", ") || "nothing") + "; inputs: " + (seen.join("; ") || "none")); } catch {}
    location.replace(fallback);
    return ABORT;
  }

  (async () => {
    const cfg = await settings();
    // "dupdirect" marks a page that should be used as it is: the prompt is
    // ready, or the project page has already been tried.
    const direct = url.searchParams.get("dupdirect") === "1";
    const home = cfg.project ? "/project/" + cfg.project : "/new";

    // Right-click menu: the background script holds the selected text under a
    // one-time id and opens /new with that id. A link from anywhere else has
    // no text waiting for it, so nothing happens.
    if (jobId) {
      if (cfg.project && !onProject && !direct) {
        location.replace(link(home, { dupjob: jobId }));
        return;
      }
      let job = null;
      try { job = await chrome.runtime.sendMessage({ type: "dupjob", id: jobId }); } catch {}
      const template = job && cfg.jobs[job.mode];
      if (!template) return;
      const text = fillPrompt(template, "text", { text: job.text, url: job.url });
      sendOn(
        cfg.model,
        () => (onProject ? typeOnProject(text, link("/new", { dupjob: jobId, dupdirect: 1 })) : typePrompt(text)),
        () => { try { chrome.runtime.sendMessage({ type: "dupjob-done", id: jobId }); } catch {} }
      );
      return;
    }

    // Searches arrive as the bare query. Reload once with the preamble in front;
    // claude.ai fills the prompt from the URL, so that is the place to add it.
    // With a project set, that reload goes to the project's page instead of /new,
    // so the chat starts inside the project.
    const q = url.searchParams.get("q") || "";
    if (!q) return;
    if (!direct) {
      const prompt = fillPrompt(cfg.preamble, "query", { query: q });
      location.replace(link(home, { q: prompt, dupsearch: TOKEN, dupdirect: 1 }));
      return;
    }
    sendOn(cfg.model, () => (onProject
      ? typeOnProject(q, link("/new", { q, dupsearch: TOKEN, dupdirect: 1 }))
      : waitFor(() => { const b = promptBox(); return b && b.innerText.trim() ? b : null; })));
  })();
})();
