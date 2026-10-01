// Claude as Default Search, v3.
// Address-bar searches carry a secret token. Links from anywhere else don't,
// so Claude's normal "use caution" stop still applies to them.
(() => {
  const TOKEN = "__TOKEN__";
  const WANT_ID = "claude-sonnet-5-5"; // model for quick searches
  const WANT_NAME = "Sonnet";
  const USUAL_KEY = "dupsearch-usual-model";

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

  const isSearch = new URL(location.href).searchParams.get("dupsearch") === TOKEN;

  // Normal visits: just note which model you usually use, so searches can put it back.
  if (!isSearch) {
    waitFor(pickerLabel, 15000, 250).then((l) => {
      const id = idFromLabel(l);
      if (id && !l.includes(WANT_NAME)) store.set(id);
    });
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
        .find((e) => e.offsetParent !== null && e.innerText.trim())
    );
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
