// Right-click menu for selected text: Search, Ask, Summarize.
const TOKEN = "__TOKEN__";
const ITEMS = {
  "claude-search": "Search with Claude",
  "claude-ask": "Ask about this",
  "claude-summarize": "Summarize",
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "claude", title: "Claude", contexts: ["selection"] });
    for (const [id, title] of Object.entries(ITEMS)) {
      chrome.contextMenus.create({ id, parentId: "claude", title, contexts: ["selection"] });
    }
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const text = (info.selectionText || "").trim();
  if (!text || !(info.menuItemId in ITEMS)) return;
  const url = new URL("https://claude.ai/new");
  if (info.menuItemId === "claude-search") {
    // Same as typing the selection into the address bar, so keep it to one line.
    url.searchParams.set("q", text.replace(/\s+/g, " "));
    url.searchParams.set("dupsearch", TOKEN);
  } else {
    // The text waits here under a one-time id; autosend.js collects it from the new tab.
    const id = crypto.randomUUID();
    const mode = info.menuItemId.replace("claude-", "");
    await chrome.storage.session.set({ ["job-" + id]: { mode, text, url: info.pageUrl || "" } });
    url.searchParams.set("dupjob", id);
  }
  chrome.tabs.create({ url: url.href, ...(tab ? { index: tab.index + 1, openerTabId: tab.id } : {}) });
});

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || msg.type !== "dupjob" || sender.id !== chrome.runtime.id) return;
  const key = "job-" + msg.id;
  chrome.storage.session.get(key).then((found) => {
    chrome.storage.session.remove(key);
    reply(found[key] || null);
  });
  return true;
});
