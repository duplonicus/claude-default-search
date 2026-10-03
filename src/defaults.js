// The prompts the extension sends, and the project it was built with.
// Change them on the extension's options page; these are what it falls back to.
// MODELS is what the options page offers: `id` is what claude.ai's model picker
// stores, `name` is the word to look for in the picker's label.
// {query} is what you typed; {text} is the text you selected and {url} the page it was on.
const BUILT_PROJECT = "__PROJECT__";
const MODELS = [
  { id: "claude-sonnet-5-5", name: "Sonnet", label: "Sonnet 5.5" },
  { id: "claude-haiku-4-5", name: "Haiku", label: "Haiku 4.5" },
  { id: "claude-opus-5-5", name: "Opus", label: "Opus 5.5" },
  { id: "claude-fable-5-1", name: "Fable", label: "Fable 5.1" },
];
const NO_SWITCH = "none"; // saved as the model when searches should use your usual one
const DEFAULTS = {
  // The model searches and right-click requests run on.
  model: "claude-sonnet-5-5",
  // Goes in front of every search, so the model knows it's being used as a
  // search engine and isn't handed two bare words with no context.
  preamble:
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
    "Search query: {query}",
  // Right-click menu on selected text.
  ask:
    "This is not a search query. Explain the text below, which I selected on a web page. " +
    "If it's a question, answer it; if it's in another language, translate it. Lead with " +
    "the answer in a sentence or two and keep it brief.\n\n" +
    "From: {url}\n\n" +
    "{text}",
  summarize:
    "This is not a search query. Summarize the text below, which I selected on a web page. " +
    "Give the main point in a sentence or two, then the key details as a short list. Work " +
    "only from this text; don't look the page up.\n\n" +
    "From: {url}\n\n" +
    "{text}",
};
const PROJECT_ID = /[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}/;
// Puts the values into a prompt. A prompt that leaves out its main placeholder
// still gets the value, on its own line at the end.
function fillPrompt(template, main, values) {
  const out = template.replace(/\{(\w+)\}/g, (whole, key) => (key in values ? values[key] : whole));
  return template.includes("{" + main + "}") ? out : out + "\n\n" + values[main];
}
