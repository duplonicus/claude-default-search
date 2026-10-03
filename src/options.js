// Options page: the project link and the three prompts, kept in the extension's own storage.
const PROMPTS = ["preamble", "ask", "summarize"];
const field = (id) => document.getElementById(id);
const say = (text, kind = "") => {
  field("status").textContent = text;
  field("status").dataset.kind = kind;
};

async function show() {
  const saved = await chrome.storage.local.get([...PROMPTS, "projectUrl"]);
  // A prompt that was never changed shows the default, so there is something to edit.
  for (const k of PROMPTS) field(k).value = saved[k] || DEFAULTS[k];
  field("projectUrl").value = saved.projectUrl || "";
  const built = BUILT_PROJECT.match(PROJECT_ID);
  field("projectUrl").placeholder = built
    ? "https://claude.ai/project/" + built[0] + " (chosen at setup)"
    : "https://claude.ai/project/...";
}

field("save").addEventListener("click", async () => {
  const projectUrl = field("projectUrl").value.trim();
  if (projectUrl && !PROJECT_ID.test(projectUrl)) {
    say("That link has no project id in it. Expected https://claude.ai/project/<id>.", "error");
    return;
  }
  const values = { projectUrl };
  // An untouched default isn't saved, so later improvements to the defaults still reach you.
  for (const k of PROMPTS) {
    const text = field(k).value.trim();
    values[k] = text === DEFAULTS[k].trim() ? "" : text;
  }
  await chrome.storage.local.set(values);
  await show();
  say("Saved.");
});

field("reset").addEventListener("click", async () => {
  await chrome.storage.local.remove(PROMPTS);
  await show();
  say("Prompts reset to the defaults. The project link was kept.");
});

show();
