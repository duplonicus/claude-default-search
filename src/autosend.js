// Claude as Default Search, v3.2.
// Address-bar searches carry a secret token. Links from anywhere else don't,
// so Claude's normal "use caution" stop still applies to them.
(() => {
  const TOKEN = "__TOKEN__";
  const WANT_ID = "claude-sonnet-5-5"; // model for quick searches
  const WANT_NAME = "Sonnet";
  const USUAL_KEY = "dupsearch-usual-model";
  const MISS_KEY = "dupsearch-project-miss";
  // Optional: the id of a claude.ai project to file searches in.
  const PROJECT = "__PROJECT__";
  const HAS_PROJECT = /^[0-9a-f-]{36}$/.test(PROJECT);
  // Goes in front of every search, so the model knows it's being used as a
  // search engine and isn't handed two bare words with no context.
  const PREAMBLE =
    "I typed the text below into my browser's address bar, which sends my searches " +
    "to you instead of a search engine. Treat it as a search query, not a chat message: " +
    "it may be a few keywords, a site name or a full question. Search the web unless " +
    "the answer can't have changed recently. Lead with the answer in a sentence or two, " +
    "then the most useful results as a short list of links, each with a line on what " +
    "it is. Link inline as well: wherever the text names a page, product, person or " +
    "source, make that name the hyperlink, so I can click straight from the sentence. " +
    "If I'm clearly just trying to get to a site, give me its link first. " +
    "Don't ask what I meant; go with the most likely reading and mention the others " +
    "only if they'd change the answer.\n\n" +
    "Search query: ";

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

  const url = new URL(location.href);
  const isSearch = url.searchParams.get("dupsearch") === TOKEN;

  // Normal visits: just note which model you usually use, so searches can put it back.
  if (!isSearch) {
    waitFor(pickerLabel, 15000, 250).then((l) => {
      const id = idFromLabel(l);
      if (id && !l.includes(WANT_NAME)) store.set(id);
    });
    return;
  }

  // Searches arrive as the bare query. Reload once with the preamble in front;
  // claude.ai fills the prompt from the URL, so that is the place to add it.
  // With a project set, that reload goes to the project's page instead of /new,
  // so the chat starts inside the project.
  const searchUrl = (path, query) => {
    const u = new URL(path, location.origin);
    u.searchParams.set("q", query);
    u.searchParams.set("dupsearch", TOKEN);
    return u.href;
  };
  const q = url.searchParams.get("q") || "";
  const onProject = location.pathname.startsWith("/project/");
  if (q && !q.startsWith(PREAMBLE)) {
    location.replace(searchUrl(HAS_PROJECT ? "/project/" + PROJECT : "/new", PREAMBLE + q));
    return;
  }

  // Searches: switch the account to Sonnet before claude.ai loads its settings,
  // so the page opens on Sonnet with no clicking.
  const usual = store.get() || "claude-opus-5-5";
  const preset = setAccountModel(WANT_ID);

  (async () => {
    await preset;
    const box = await waitFor(() =>
      [...document.querySelectorAll('[aria-label="Write your prompt to Claude"]')]
        .find((e) => e.offsetParent !== null && e.innerText.trim()),
      onProject ? 6000 : 15000
    );
    // The project page didn't fill the prompt: note what was there, then run
    // the search from /new so it still goes through.
    if (!box && onProject) {
      const seen = [...document.querySelectorAll('[contenteditable="true"], textarea')]
        .map((e) => (ariaLabel(e) || e.tagName) + ((e.innerText || e.value || "").trim() ? " (filled)" : " (empty)"));
      try { localStorage.setItem(MISS_KEY, new Date().toISOString() + " inputs: " + (seen.join("; ") || "none")); } catch {}
      location.replace(searchUrl("/new", q));
      return;
    }
    const send = box && await waitFor(() =>
      buttons().find((b) => ariaLabel(b) === "Send message" && !b.disabled)
    );

    // Fallback: if the page still came up on another model, use the picker.
    if (send && !(pickerLabel() || "").includes(WANT_NAME)) {
      const p = buttons().find((x) => ariaLabel(x).startsWith("Model:"));
      if (p) {
        p.click();
        const item = await waitFor(() =>
          [...document.querySelectorAll('[role="menuitemradio"]')]
            .find((m) => m.textContent.includes(WANT_NAME)), 2000);
        if (item) item.click();
        await waitFor(() => (pickerLabel() || "").includes(WANT_NAME), 2000);
      }
    }
    if (send) send.click();

    // Put your usual model back once the chat exists.
    await waitFor(() => location.pathname.startsWith("/chat/"), 8000, 100);
    await sleep(1000);
    await setAccountModel(usual);
  })();
})();
