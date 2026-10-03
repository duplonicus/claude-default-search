"""Runs the extension's content script in headless Chromium against a stand-in for claude.ai.

The stand-in copies the behaviour the script relies on: /new fills the prompt from ?q=, a project
page doesn't, the prompt box is a ProseMirror editor (tiptap, loaded from esm.sh, so these tests
need network), and Send moves the page to /chat/<id>.
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
TOKEN = "testtoken"
PROJECT = "01234567-89ab-cdef-0123-456789abcdef"
ORG = "org-1"

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


def built(project=None):
    js = SRC.read_text().replace("__TOKEN__", TOKEN)
    return js.replace("__PROJECT__", project) if project else js


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
def preamble(browser):
    expr = re.search(r"const PREAMBLE =\n(.*?);\n", SRC.read_text(), re.S).group(1)
    page = browser.new_page()
    text = page.evaluate("() => " + expr)
    page.close()
    return text


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


MODEL_CALL = ("PATCH", f"/api/organizations/{ORG}/model_selector_state/chat")


def test_search_without_project_sends_from_new_with_preamble(browser, preamble):
    page, patches = open_site(browser, built())
    search(page)
    page.wait_for_function("window.sent", timeout=20000)
    head, tail = preamble.split("\n\n")
    assert page.evaluate("window.sent") == {"from": "/new", "paragraphs": [head, "", tail + "weather boston"]}
    page.wait_for_timeout(1500)  # the usual model goes back about a second after the chat exists
    assert patches == [(*MODEL_CALL, {"model": "claude-sonnet-5-5"}), (*MODEL_CALL, {"model": "claude-opus-5-5"})]


def test_search_with_project_types_prompt_on_project_page(browser, preamble):
    page, patches = open_site(browser, built(PROJECT))
    search(page, 'cats & "dogs"')
    page.wait_for_function("window.sent", timeout=20000)
    head, tail = preamble.split("\n\n")
    assert page.evaluate("window.sent") == {
        "from": f"/project/{PROJECT}",
        "paragraphs": [head, "", tail + 'cats & "dogs"'],
    }
    page.wait_for_timeout(1500)
    assert patches == [(*MODEL_CALL, {"model": "claude-sonnet-5-5"}), (*MODEL_CALL, {"model": "claude-opus-5-5"})]
    assert page.evaluate("localStorage.getItem('dupsearch-project-miss')") is None


def test_unusable_project_page_falls_back_to_new(browser, preamble):
    page, _ = open_site(browser, built(PROJECT), project_html=NO_EDITOR)
    search(page)
    page.wait_for_function("window.sent", timeout=30000)
    head, tail = preamble.split("\n\n")
    assert page.evaluate("window.sent") == {"from": "/new", "paragraphs": [head, "", tail + "weather boston"]}
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
    js = (tmp_path / "extension" / "autosend.js").read_text()
    manifest = (tmp_path / "extension" / "manifest.json").read_text()
    assert re.search(r'const PROJECT = "([^"]*)"', js).group(1) == expected
    background = (tmp_path / "extension" / "background.js").read_text()
    token = re.search(r'const TOKEN = "([^"]*)"', js).group(1)
    assert re.fullmatch(r"[0-9a-f]{24}", token)
    assert json.loads(manifest)["chrome_settings_overrides"]["search_provider"]["search_url"].endswith(token)
    assert re.search(r'const TOKEN = "([^"]*)"', background).group(1) == token
    assert "__TOKEN__" not in js + manifest + background


def test_setup_sh_rejects_a_link_with_no_project_id(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "setup.sh", tmp_path)
    (tmp_path / ".env").write_text("PROJECT_URL=https://claude.ai/projects\n")
    result = subprocess.run(["sh", "setup.sh"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert not (tmp_path / "extension").exists()


# --- Right-click menu -------------------------------------------------------------------------

SELECTION = "First  line of the   selection\nSecond line\n\n\n\nAfter a gap"
PAGE_URL = "https://example.com/article"


def job_prompt(browser, mode):
    """The prompt the script builds for a job, read from the source."""
    block = re.search(r"const JOBS = \{.*?\n  \};", SRC.read_text(), re.S).group(0)
    page = browser.new_page()
    text = page.evaluate("(j) => { %s; return JOBS[j.mode](j); }" % block,
                         {"mode": mode, "text": SELECTION, "url": PAGE_URL})
    page.close()
    return text


def as_paragraphs(text):
    """What the prompt box should hold: a paragraph per line, spaces collapsed, one blank line at most."""
    return [re.sub(r"\s+", " ", line) for line in re.sub(r"\n{3,}", "\n\n", text).split("\n")]


def with_jobs(script, jobs):
    """Stands in for the background script, which hands the selected text to the page."""
    stub = "window.chrome = window.chrome || {}; window.chrome.runtime = {sendMessage: async (m) => (%s)[m.id] || null};"
    return stub % json.dumps(jobs) + script


@pytest.mark.parametrize("mode", ["summarize", "ask"])
def test_right_click_job_is_typed_and_sent_on_sonnet(browser, mode):
    prompt = job_prompt(browser, mode)
    assert SELECTION in prompt and PAGE_URL in prompt
    jobs = {"j1": {"mode": mode, "text": SELECTION, "url": PAGE_URL}}
    page, patches = open_site(browser, with_jobs(built(PROJECT), jobs))
    page.goto("https://claude.ai/new?dupjob=j1")
    page.wait_for_function("window.sent", timeout=20000)
    sent = page.evaluate("window.sent")
    assert sent == {"from": "/new", "paragraphs": as_paragraphs(prompt)}
    assert sent["paragraphs"][-4:] == ["First line of the selection", "Second line", "", "After a gap"]
    page.wait_for_timeout(1500)
    assert patches == [(*MODEL_CALL, {"model": "claude-sonnet-5-5"}), (*MODEL_CALL, {"model": "claude-opus-5-5"})]


def test_job_link_with_nothing_waiting_does_nothing(browser):
    page, patches = open_site(browser, with_jobs(built(PROJECT), {}))
    page.goto("https://claude.ai/new?dupjob=made-up")
    page.wait_for_selector('[aria-label="Write your prompt to Claude"]')
    page.wait_for_timeout(1500)
    assert page.evaluate("window.sent") is None
    assert page.evaluate("document.querySelector('[aria-label=\"Write your prompt to Claude\"]').innerText.trim()") == ""
    assert patches == []


@pytest.fixture
def installed(pw, tmp_path):
    """The built extension loaded into a real browser profile, with claude.ai replaced by the stand-in."""
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


@pytest.mark.parametrize("mode", ["summarize", "ask"])
def test_installed_extension_menu_click_opens_claude_and_sends(browser, installed, mode):
    ctx, worker, patches, _ = installed
    page, link = click_menu(ctx, worker, "claude-" + mode)
    page.wait_for_function("window.sent", timeout=20000)
    assert page.evaluate("window.sent") == {"from": "/new", "paragraphs": as_paragraphs(job_prompt(browser, mode))}
    assert patches[0] == (*MODEL_CALL, {"model": "claude-sonnet-5-5"})
    # The text is handed over once: opening the same link again must not send anything.
    again = ctx.new_page()
    again.goto(link)
    again.wait_for_selector('[aria-label="Write your prompt to Claude"]')
    again.wait_for_timeout(1500)
    assert again.evaluate("window.sent") is None


def test_installed_extension_search_item_runs_a_normal_search(installed, preamble):
    ctx, worker, _, ext = installed
    page, link = click_menu(ctx, worker, "claude-search")
    token = re.search(r'const TOKEN = "([^"]*)"', (ext / "background.js").read_text()).group(1)
    assert f"dupsearch={token}" in link
    page.wait_for_function("window.sent", timeout=20000)
    head, tail = preamble.split("\n\n")
    assert page.evaluate("window.sent") == {"from": "/new", "paragraphs": [head, "", tail + re.sub(r"\s+", " ", SELECTION)]}
