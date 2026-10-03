"""Runs the extension in headless Chromium against a stand-in for claude.ai.

The stand-in copies the behaviour the extension relies on: /new fills the prompt from ?q=, a project
page doesn't, the prompt box is a ProseMirror editor (tiptap, loaded from esm.sh, so these tests
need network), and Send moves the page to /chat/<id>.

Most tests inject the content script into the stand-in with the extension's own APIs stubbed. The
"installed" tests load the built extension into a real browser profile instead.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get("AUTOSEND_SRC", ROOT / "src" / "autosend.js"))
DEFAULTS_SRC = ROOT / "src" / "defaults.js"
TOKEN = "testtoken"
PROJECT = "01234567-89ab-cdef-0123-456789abcdef"
OTHER_PROJECT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ORG = "org-1"
BOX = '[aria-label="Write your prompt to Claude"]'

PAGE = """<!doctype html><button aria-label="Model: Sonnet 5.5">Sonnet</button>
<div id="ed"></div><button id="send" aria-label="Send message" disabled>Send</button>
<script type="module">
import {Editor} from 'https://esm.sh/@tiptap/core@2';
import StarterKit from 'https://esm.sh/@tiptap/starter-kit@2';
const send = document.querySelector('#send');
const ed = new Editor({element: document.querySelector('#ed'), extensions: [StarterKit],
  editorProps: {attributes: {'aria-label': 'Write your prompt to Claude'}},
  onUpdate: ({editor}) => { send.disabled = editor.isEmpty; }});
const q = new URLSearchParams(location.search).get('q');
if (location.pathname === '/new' && q) {
  ed.commands.setContent(q.split('\\n').map((l) => {
    const p = document.createElement('p'); p.textContent = l; return p.outerHTML; }).join(''));
  send.disabled = ed.isEmpty;
}
send.addEventListener('click', () => {
  window.sent = {from: location.pathname,
    paragraphs: ed.getJSON().content.map((n) => (n.content || []).map((t) => t.text || '').join(''))};
  history.pushState({}, '', '/chat/abc');
});
</script>"""
NO_EDITOR = "<!doctype html><p>project page with no prompt box</p>"

SELECTION = "First  line of the   selection\nSecond line\n\n\n\nAfter a gap"
PAGE_URL = "https://example.com/article"


def built(project=None, jobs=None, saved=None):
    """The content scripts as setup would build them, with the extension's APIs stubbed.

    `jobs` is what the background script is holding; `saved` is what the options page stored.
    """
    js = DEFAULTS_SRC.read_text() + "\n" + SRC.read_text().replace("__TOKEN__", TOKEN)
    if project:
        js = js.replace("__PROJECT__", project)
    stub = """window.chrome = window.chrome || {};
window.chrome.storage = {local: {get: async () => (%s)}};
window.chrome.runtime = {sendMessage: async (m) => {
  if (m.type === 'dupjob-done') { (window.doneJobs = window.doneJobs || []).push(m.id); return; }
  return (%s)[m.id] || null; }};
""" % (json.dumps(saved or {}), json.dumps(jobs or {}))
    return stub + js


@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture(scope="module")
def defaults(browser):
    """The default prompts, read from defaults.js."""
    page = browser.new_page()
    found = page.evaluate("() => { %s; return DEFAULTS; }" % DEFAULTS_SRC.read_text())
    page.close()
    assert set(found) == {"preamble", "ask", "summarize"}
    return found


def as_paragraphs(text):
    """What the prompt box should hold: a paragraph per line, spaces collapsed, one blank line at most."""
    return [re.sub(r"\s+", " ", line) for line in re.sub(r"\n{3,}", "\n\n", text).split("\n")]


def search_prompt(defaults, query):
    assert defaults["preamble"].endswith("\n\nSearch query: {query}")
    return defaults["preamble"].replace("{query}", query)


def job_prompt(defaults, mode):
    template = defaults[mode]
    assert "{text}" in template and "{url}" in template
    return template.replace("{url}", PAGE_URL).replace("{text}", SELECTION)


def open_site(browser, script, project_html=PAGE):
    """A page where claude.ai is the stand-in and `script` runs at document start, like a content script."""
    ctx = browser.new_context()
    ctx.add_cookies([{"name": "lastActiveOrg", "value": ORG, "domain": "claude.ai", "path": "/"}])
    patches = []

    def handle(route):
        req = route.request
        path = req.url.split("claude.ai", 1)[1].split("?")[0]
        if path.startswith("/api/"):
            patches.append((req.method, path, json.loads(req.post_data or "{}")))
            return route.fulfill(status=200, body="{}", content_type="application/json")
        html = project_html if path.startswith("/project/") else PAGE
        route.fulfill(status=200, body=html, content_type="text/html")

    ctx.route("https://claude.ai/**", handle)
    ctx.add_init_script(script)
    return ctx.new_page(), patches


def search(page, query="weather boston", token=TOKEN):
    page.goto(f"https://claude.ai/new?q={quote_plus(query)}&dupsearch={token}")


def sent(page, timeout=20000):
    page.wait_for_function("window.sent", timeout=timeout)
    return page.evaluate("window.sent")


MODEL_CALL = ("PATCH", f"/api/organizations/{ORG}/model_selector_state/chat")
SONNET_THEN_USUAL = [(*MODEL_CALL, {"model": "claude-sonnet-5-5"}), (*MODEL_CALL, {"model": "claude-opus-5-5"})]


# --- Address-bar searches ---------------------------------------------------------------------


def test_search_without_project_sends_from_new_with_preamble(browser, defaults):
    page, patches = open_site(browser, built())
    search(page)
    assert sent(page) == {"from": "/new", "paragraphs": as_paragraphs(search_prompt(defaults, "weather boston"))}
    assert sent(page)["paragraphs"][-2:] == ["", "Search query: weather boston"]
    page.wait_for_timeout(1500)  # the usual model goes back about a second after the chat exists
    assert patches == SONNET_THEN_USUAL


def test_search_with_project_types_prompt_on_project_page(browser, defaults):
    page, patches = open_site(browser, built(PROJECT))
    search(page, 'cats & "dogs"')
    assert sent(page) == {
        "from": f"/project/{PROJECT}",
        "paragraphs": as_paragraphs(search_prompt(defaults, 'cats & "dogs"')),
    }
    page.wait_for_timeout(1500)
    assert patches == SONNET_THEN_USUAL
    assert page.evaluate("localStorage.getItem('dupsearch-project-miss')") is None


def test_unusable_project_page_falls_back_to_new(browser, defaults):
    page, _ = open_site(browser, built(PROJECT), project_html=NO_EDITOR)
    search(page)
    assert sent(page, 30000) == {"from": "/new", "paragraphs": as_paragraphs(search_prompt(defaults, "weather boston"))}
    note = page.evaluate("localStorage.getItem('dupsearch-project-miss')")
    assert note.endswith("tried: nothing; inputs: none")


@pytest.mark.parametrize("token", ["wrong", ""])
def test_links_without_the_secret_are_left_alone(browser, token):
    page, patches = open_site(browser, built(PROJECT))
    search(page, token=token)
    page.wait_for_selector('[aria-label="Send message"]:not([disabled])')  # prompt filled, as claude.ai does
    page.wait_for_timeout(1500)
    assert page.evaluate("window.sent") is None
    assert page.evaluate("location.pathname") == "/new"
    assert patches == []


# --- Options ----------------------------------------------------------------------------------


def test_saved_prompt_and_project_replace_the_defaults(browser):
    saved = {"preamble": "Look this up: {query} (be brief)", "projectUrl": f"https://claude.ai/project/{OTHER_PROJECT}"}
    page, _ = open_site(browser, built(PROJECT, saved=saved))
    search(page)
    assert sent(page) == {"from": f"/project/{OTHER_PROJECT}", "paragraphs": ["Look this up: weather boston (be brief)"]}


def test_saved_prompt_without_a_placeholder_still_gets_the_query(browser):
    page, _ = open_site(browser, built(saved={"preamble": "Answer in French."}))
    search(page)
    assert sent(page) == {"from": "/new", "paragraphs": ["Answer in French.", "", "weather boston"]}


def test_empty_saved_values_mean_the_defaults(browser, defaults):
    page, _ = open_site(browser, built(PROJECT, saved={"preamble": "  ", "projectUrl": ""}))
    search(page)
    assert sent(page) == {
        "from": f"/project/{PROJECT}",
        "paragraphs": as_paragraphs(search_prompt(defaults, "weather boston")),
    }


# --- Right-click menu -------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["summarize", "ask"])
@pytest.mark.parametrize("project,home", [(None, "/new"), (PROJECT, f"/project/{PROJECT}")])
def test_right_click_job_is_typed_and_sent_on_sonnet(browser, defaults, mode, project, home):
    jobs = {"j1": {"mode": mode, "text": SELECTION, "url": PAGE_URL}}
    page, patches = open_site(browser, built(project, jobs=jobs))
    page.goto("https://claude.ai/new?dupjob=j1")
    got = sent(page)
    assert got == {"from": home, "paragraphs": as_paragraphs(job_prompt(defaults, mode))}
    assert got["paragraphs"][-6:] == ["From: " + PAGE_URL, "", "First line of the selection", "Second line", "", "After a gap"]
    page.wait_for_timeout(1500)
    assert patches == SONNET_THEN_USUAL
    assert page.evaluate("window.doneJobs") == ["j1"]


def test_right_click_job_falls_back_to_new_when_the_project_page_is_unusable(browser, defaults):
    jobs = {"j1": {"mode": "summarize", "text": SELECTION, "url": PAGE_URL}}
    page, _ = open_site(browser, built(PROJECT, jobs=jobs), project_html=NO_EDITOR)
    page.goto("https://claude.ai/new?dupjob=j1")
    assert sent(page, 30000) == {"from": "/new", "paragraphs": as_paragraphs(job_prompt(defaults, "summarize"))}


def test_selected_text_containing_a_placeholder_is_sent_as_written(browser):
    jobs = {"j1": {"mode": "ask", "text": "what does {url} mean in a template?", "url": PAGE_URL}}
    page, _ = open_site(browser, built(jobs=jobs, saved={"ask": "{text} | seen on {url}"}))
    page.goto("https://claude.ai/new?dupjob=j1")
    assert sent(page)["paragraphs"] == ["what does {url} mean in a template? | seen on " + PAGE_URL]


@pytest.mark.parametrize("project", [None, PROJECT])
def test_job_link_with_nothing_waiting_does_nothing(browser, project):
    page, patches = open_site(browser, built(project))
    page.goto("https://claude.ai/new?dupjob=made-up")
    page.wait_for_selector(BOX)
    page.wait_for_timeout(1500)
    assert page.evaluate("window.sent") is None
    assert page.evaluate(f"document.querySelector('{BOX}').innerText.trim()") == ""
    assert patches == []


# --- The built extension, loaded into a real browser profile ----------------------------------


@pytest.fixture
def installed(pw, tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "setup.sh", tmp_path)
    subprocess.run(["sh", "setup.sh"], cwd=tmp_path, check=True, capture_output=True)
    ext = tmp_path / "extension"
    ctx = pw.chromium.launch_persistent_context(
        str(tmp_path / "profile"), channel="chromium", headless=True,
        # The tab the extension opens starts loading before the stand-in can be attached to it, so
        # claude.ai is made unreachable: that first load fails, and the test loads the same link again.
        args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}",
              "--host-resolver-rules=MAP claude.ai ~NOTFOUND"])
    ctx.add_cookies([{"name": "lastActiveOrg", "value": ORG, "domain": "claude.ai", "path": "/"}])
    patches = []

    def handle(route):
        req = route.request
        path = req.url.split("claude.ai", 1)[1].split("?")[0]
        if path.startswith("/api/"):
            patches.append((req.method, path, json.loads(req.post_data or "{}")))
            return route.fulfill(status=200, body="{}", content_type="application/json")
        route.fulfill(status=200, body=PAGE, content_type="text/html")

    ctx.route("https://claude.ai/**", handle)
    worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
    yield ctx, worker, patches, ext
    ctx.close()


def click_menu(ctx, worker, item):
    """Fires the menu item as a right-click would, and returns the tab it opened, loaded on the stand-in."""
    worker.evaluate("""() => {
        const create = chrome.tabs.create.bind(chrome.tabs);
        chrome.tabs.create = (options) => { self.openedLink = options.url; return create(options); };
    }""")
    with ctx.expect_page() as opened:
        worker.evaluate(
            "(info) => chrome.contextMenus.onClicked.dispatch(info, undefined)",
            {"menuItemId": item, "selectionText": SELECTION, "pageUrl": PAGE_URL})
    page = opened.value
    page.wait_for_load_state()
    link = worker.evaluate("self.openedLink")
    assert link.startswith("https://claude.ai/new?"), link
    page.goto(link)
    return page, link


def until(page, expression, timeout=5000):
    """Waits for `expression` to be true. Extension pages forbid the way wait_for_function polls."""
    for _ in range(timeout // 50):
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError("never became true: " + expression)


def options_page(ctx, worker):
    page = ctx.new_page()
    page.goto(worker.url.replace("background.js", "options.html"))
    until(page, "document.getElementById('preamble').value.length > 0")
    return page


@pytest.mark.parametrize("mode", ["summarize", "ask"])
def test_installed_extension_menu_click_opens_claude_and_sends(defaults, installed, mode):
    ctx, worker, patches, _ = installed
    page, link = click_menu(ctx, worker, "claude-" + mode)
    assert sent(page) == {"from": "/new", "paragraphs": as_paragraphs(job_prompt(defaults, mode))}
    assert patches[0] == (*MODEL_CALL, {"model": "claude-sonnet-5-5"})
    # The text is handed over once: opening the same link again must not send anything.
    again = ctx.new_page()
    again.goto(link)
    again.wait_for_selector(BOX)
    again.wait_for_timeout(1500)
    assert again.evaluate("window.sent") is None


def test_installed_extension_search_item_runs_a_normal_search(defaults, installed):
    ctx, worker, _, ext = installed
    page, link = click_menu(ctx, worker, "claude-search")
    token = re.search(r'const TOKEN = "([^"]*)"', (ext / "background.js").read_text()).group(1)
    assert f"dupsearch={token}" in link
    one_line = re.sub(r"\s+", " ", SELECTION)
    assert sent(page) == {"from": "/new", "paragraphs": as_paragraphs(search_prompt(defaults, one_line))}


def test_options_page_shows_defaults_and_its_settings_take_effect(defaults, installed):
    ctx, worker, _, _ = installed
    options = options_page(ctx, worker)
    for key in ("preamble", "ask", "summarize"):
        assert options.input_value("#" + key) == defaults[key]
    assert options.input_value("#projectUrl") == ""

    options.fill("#projectUrl", "https://claude.ai/project/nope")
    options.click("#save")
    until(options, "document.getElementById('status').textContent.includes('no project id')")
    assert worker.evaluate("chrome.storage.local.get(null)") == {}

    options.fill("#projectUrl", f"https://claude.ai/project/{OTHER_PROJECT}")
    options.fill("#summarize", "TL;DR this: {text}")
    options.click("#save")
    until(options, "document.getElementById('status').textContent === 'Saved.'")
    # Only what was changed is stored; untouched prompts keep following the defaults.
    assert worker.evaluate("chrome.storage.local.get(null)") == {
        "projectUrl": f"https://claude.ai/project/{OTHER_PROJECT}",
        "preamble": "", "ask": "", "summarize": "TL;DR this: {text}"}

    page, _ = click_menu(ctx, worker, "claude-summarize")
    assert sent(page) == {"from": f"/project/{OTHER_PROJECT}", "paragraphs": as_paragraphs("TL;DR this: " + SELECTION)}

    options.click("#reset")
    until(options, "document.getElementById('status').textContent.startsWith('Prompts reset')")
    assert options.input_value("#summarize") == defaults["summarize"]
    assert options.input_value("#projectUrl") == f"https://claude.ai/project/{OTHER_PROJECT}"


# --- setup.sh ---------------------------------------------------------------------------------

ENV_CASES = [
    (None, "__PROJECT__"),
    ("PROJECT_URL=\n", "__PROJECT__"),
    (f"#PROJECT_URL=https://claude.ai/project/{PROJECT}\n", "__PROJECT__"),
    (f"PROJECT_URL=https://claude.ai/project/{PROJECT}\n", PROJECT),
    (f'PROJECT_URL="https://claude.ai/project/{PROJECT}"\r\n', PROJECT),
]


@pytest.mark.parametrize("env,expected", ENV_CASES)
def test_setup_sh_bakes_in_the_project_only_when_set(tmp_path, env, expected):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "setup.sh", tmp_path)
    if env is not None:
        (tmp_path / ".env").write_bytes(env.encode())
    subprocess.run(["sh", "setup.sh"], cwd=tmp_path, check=True, capture_output=True)
    out = tmp_path / "extension"
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in (ROOT / "src").iterdir())
    files = {p.name: p.read_text() for p in out.iterdir()}
    assert re.search(r'const BUILT_PROJECT = "([^"]*)"', files["defaults.js"]).group(1) == expected
    token = re.search(r'const TOKEN = "([^"]*)"', files["autosend.js"]).group(1)
    assert re.fullmatch(r"[0-9a-f]{24}", token)
    assert re.search(r'const TOKEN = "([^"]*)"', files["background.js"]).group(1) == token
    manifest = json.loads(files["manifest.json"])
    assert manifest["chrome_settings_overrides"]["search_provider"]["search_url"].endswith(token)
    assert "__TOKEN__" not in "".join(files.values())
    # Everything the manifest points at was built.
    named = [manifest["background"]["service_worker"], manifest["options_ui"]["page"],
             *manifest["content_scripts"][0]["js"]]
    assert set(named) <= set(files)


def test_setup_sh_rejects_a_link_with_no_project_id(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "setup.sh", tmp_path)
    (tmp_path / ".env").write_text("PROJECT_URL=https://claude.ai/projects\n")
    result = subprocess.run(["sh", "setup.sh"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert not (tmp_path / "extension").exists()
