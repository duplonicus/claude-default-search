# Claude as Default Search

Type in the address bar, hit Enter, and the question goes straight to Claude on **Sonnet**,
sent automatically. Your regular claude.ai chats stay on your usual model (Opus, say).

Works in Brave and Chrome. Not affiliated with Anthropic.

## Why this exists

- Brave won't let a custom search engine you add by hand become the default ("Make default" is grayed out).
  Extensions can set it, so this one does.
- `claude.ai/new?q=...` fills in the prompt but no longer sends it. It shows a "use caution" banner instead,
  because a link could plant a malicious prompt. This extension presses send for you, but **only** on searches
  from your own address bar (see Security).
- claude.ai has no URL parameter for the model, so the extension sets the model itself.

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

To change the preamble or the search model, edit `PREAMBLE`, `WANT_ID` and `WANT_NAME` at the top of
`src/autosend.js` and run setup again.

## Security

- Each install gets its own random secret code. Only searches from your address bar carry it.
  A link on any other site won't have it, so claude.ai's normal "use caution" stop still applies.
  Don't share your built `extension` folder; share this repo and let people run setup.
- The extension requests no browser permissions. It only runs on `https://claude.ai/new*`
  and `https://claude.ai/project/*`, and only acts on a project page when a search sent it there.
- It sends nothing anywhere except claude.ai's own model-picker request.

## Limits

- It depends on claude.ai's page labels ("Model: ...", "Send message") and an undocumented API call.
  If claude.ai changes those, auto-send or the model switch can stop working. The search itself still
  lands in Claude; you just press Enter.
- Search-to-send takes about 2 seconds, mostly claude.ai loading.
- The preamble is part of the message, so it shows above your query in the chat.
- If you open a new chat within about a second of a search, it may start on Sonnet.
