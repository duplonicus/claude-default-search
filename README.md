# Claude as Default Search

Type in the address bar, hit Enter, and the question goes straight to Claude on **Sonnet**,
sent automatically. Your regular claude.ai chats stay on your usual model (Opus, say).

Select text on any page, right-click, and under **Claude** choose **Search with Claude**,
**Ask about this** or **Summarize**. A new tab opens next to the page and the request is sent for you.

Works in Brave and Chrome. Not affiliated with Anthropic.

## Why this exists

- Brave won't let a custom search engine you add by hand become the default ("Make default" is grayed out).
  Extensions can set it, so this one does.
- `claude.ai/new?q=...` fills in the prompt but no longer sends it. It shows a "use caution" banner instead,
  because a link could plant a malicious prompt. This extension presses send for you, but **only** on searches
  from your own address bar (see Security).
- claude.ai has no URL parameter for the model, so the extension sets the model itself.

## How it compares

| | **claude-default-search** | [Claude Search](https://chromewebstore.google.com/detail/claude-search/fjfcehgcbhdcfgempfoafdolienldgbe) | [Claude AI Search](https://chromewebstore.google.com/detail/claude-ai-search/mdpjfhahomdebomifakfombhdjnbahhi) | [Your AI in Search Bar](https://chromewebstore.google.com/detail/your-ai-in-search-bar-cha/hfcilidehpkcnlbplpfkcodijcmoamjn) | [AI Omnibox Search](https://chromewebstore.google.com/detail/ai-omnibox-search/eoglpbkepflokocokpeadckokjpjnice) |
|---|:-:|:-:|:-:|:-:|:-:|
| Plain address-bar search (no keyword) | ✅ | ✅ | ✅ | ✅ | ❌ (`ai` + space) |
| Sends automatically | ✅ | ✅ | ✅ | ✅ | — |
| Searches run on Sonnet | ✅ | — | — | — | — |
| Restores your usual model after sending | ✅ | — | — | — | — |
| Send searches to a Claude Project | ✅ | — | — | — | — |
| Right-click selected text to search, ask or summarize | ✅ | — | ✅ (ask, summarize) | — | — |
| Source on GitHub | ✅ | — | [✅](https://github.com/farhansrambiyan/claude-ai-search-extension) | — | — |

<sub>Based on each extension's Chrome Web Store listing as of October 2026, and on the GitHub source where one is linked; "—" means the listing doesn't mention it. Corrections welcome via an issue.</sub>

## Install

1. Download or clone this repo.
2. Build your personal copy (it generates your own secret code):
   - Windows: `powershell -ExecutionPolicy Bypass -File .\setup.ps1`
   - Mac/Linux: `./setup.sh`
3. Go to `brave://extensions` (or `chrome://extensions`), turn on **Developer mode**, click **Load unpacked**,
   and pick the `extension` folder.
4. If the browser asks whether to keep the search engine change, click **Keep**.

Keep the folder where it is: the browser loads the extension from it on every start.
To undo everything, remove the extension.

### Optional: file searches in a project

To keep searches out of your main chat list, make a project on claude.ai (say "Web Search"), copy
`.env.example` to `.env`, and paste the project's link:

```
PROJECT_URL=https://claude.ai/project/<id>
```

Run setup again and reload the extension. Searches now start inside that project. With no `.env`, or an
empty `PROJECT_URL`, searches are ordinary chats.

Address-bar searches carry their own instructions, so the project needs no setup. If you also want to
search by typing straight into the project on claude.ai, paste this into the project's instructions:

```
Chats in this project are web searches.

Treat the first message of each chat as a search query, not a chat message. It may be a few keywords, a site name or a full question. Search the web unless the answer can't have changed recently.

How to answer:
- Lead with the answer in a sentence or two.
- Then give the most useful results as a short list of links, each with a line on what it is.
- Link inline as well: wherever the text names a page, product, person or source, make that name the hyperlink, so I can click straight from the sentence.
- If I'm clearly just trying to get to a site, give me its link first.
- Don't ask what I meant. Go with the most likely reading and mention the others only if they'd change the answer.

Later messages in the same chat are ordinary follow-ups about the results.
```

## How it works

`manifest.json` uses `chrome_settings_overrides.search_provider` to make
`https://claude.ai/new?q={searchTerms}&dupsearch=<your secret code>` the default search.

`autosend.js` runs on `claude.ai/new` and on project pages:

1. **Normal visits:** notes which model your picker is on (your "usual" model), stored in claude.ai's localStorage.
2. **Searches (secret code present):** reloads the page once with a short preamble in front of your query,
   telling Claude the text came from the address bar and should be handled as a web search: answer first,
   then links. Without it, Claude gets two bare keywords and has to guess what you want.
   With a project set, that reload goes to the project's page. Project pages don't fill the prompt from the
   URL, so the script types it into the prompt box itself; if that fails it runs the search from
   `claude.ai/new` instead.
3. At page start, sets your claude.ai model choice to Sonnet with the same request the model picker makes
   (`PATCH /api/organizations/<org>/model_selector_state/chat`), so the page opens on Sonnet with no clicking.
   If it still opens on another model, it falls back to clicking the picker.
4. Clicks **Send** as soon as the prompt is filled in.
5. About a second after the chat is created, sets your model choice back to your usual model.

`background.js` adds the right-click menu:

- **Search with Claude** opens the same link an address-bar search would, with the selection as the query.
- **Ask about this** and **Summarize** keep the selected text and the page's address inside the extension
  under a one-time id, and open `claude.ai/new` with that id. `autosend.js` collects the text, types the
  prompt, and sends it on Sonnet. These are ordinary chats; they don't go into the project.

To change the preamble (`PREAMBLE`), the right-click prompts (`JOBS`) or the search model (`WANT_ID`,
`WANT_NAME`), edit them at the top of
`src/autosend.js` and run setup again.

## Security

- Each install gets its own random secret code. Only searches from your address bar carry it.
  A link on any other site won't have it, so claude.ai's normal "use caution" stop still applies.
  Don't share your built `extension` folder; share this repo and let people run setup.
- A right-click request can't be forged by a link either: the selected text never travels in the link,
  only a one-time id, and an id with no text waiting for it does nothing.
- The extension asks for two permissions: `contextMenus` for the right-click menu, and `storage` to hold
  the selected text until the new tab collects it (in memory only; it is cleared when the browser closes).
  It only runs on `https://claude.ai/new*`
  and `https://claude.ai/project/*`, and only acts on a project page when a search sent it there.
- It sends nothing anywhere except claude.ai: the model-picker request and the prompt itself. For Ask and
  Summarize, the prompt includes the address of the page you selected the text on.

## Limits

- It depends on claude.ai's page labels ("Model: ...", "Send message") and an undocumented API call.
  If claude.ai changes those, auto-send or the model switch can stop working. The search itself still
  lands in Claude; you just press Enter.
- Search-to-send takes about 2 seconds, mostly claude.ai loading.
- The preamble is part of the message, so it shows above your query in the chat.
- If you open a new chat within about a second of a search, it may start on Sonnet.

## Tests

```
uv venv && uv pip install pytest playwright
.venv/bin/playwright install chromium
.venv/bin/python -m pytest tests
```

The tests run the content script in headless Chromium against a stand-in for claude.ai, and run
`setup.sh` against each kind of `.env`. They need network access (the stand-in's editor loads from esm.sh).
They show the script does what it should if claude.ai behaves as it did when they were written; they
can't tell you when claude.ai changes.
