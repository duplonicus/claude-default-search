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
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
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
    token = re.search(r'const TOKEN = "([^"]*)"', js).group(1)
    assert re.fullmatch(r"[0-9a-f]{24}", token)
    assert json.loads(manifest)["chrome_settings_overrides"]["search_provider"]["search_url"].endswith(token)
    assert "__TOKEN__" not in js + manifest


def test_setup_sh_rejects_a_link_with_no_project_id(tmp_path):
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copy(ROOT / "setup.sh", tmp_path)
    (tmp_path / ".env").write_text("PROJECT_URL=https://claude.ai/projects\n")
    result = subprocess.run(["sh", "setup.sh"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 1
    assert not (tmp_path / "extension").exists()
