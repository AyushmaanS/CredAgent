import { h } from "../dom.js";
import { page, section, cards, list, callout, stats, cta } from "./parts.js";

const PRINCIPLES = [
  { tag: "1", title: "Look before you leap", text: "It researches first and writes a plan with sources, and code double-checks those sources before any browser opens." },
  { tag: "2", title: "The AI suggests, code decides", text: "The rules that keep it safe live in code, where a clever or confused model can't talk its way past them." },
  { tag: "3", title: "People keep their own steps", text: "Signing in, codes, CAPTCHAs, terms and real choices are never done on your behalf." },
  { tag: "4", title: "Working means working", text: "A live test decides how a run ends. If it didn't pass, the report says so." },
];

// How the design changed, from the decision log (D-061 to D-088) and RESULTS.md.
const STORY = [
  { tone: "plain", when: "The first design", title: "Stagehand and Jev", text: "A decision tool that forgot everything between steps, plus a step-by-step script in code." },
  { tone: "bad", when: "Discord runs 2 to 6", title: "Real pages broke it", text: "One run blocked by a bug, one I gave up on, one ran out of steps, one stalled. And it was hard to see why." },
  { tone: "plain", when: "Decision 78", title: "Start over with a simple loop", text: "One AI step at a time, driving the browser, with plain code setting the rules around it." },
  { tone: "ok", when: "Discord run 7", title: "A real credential, proven", text: "Captured from the real console and checked with a real token request." },
  { tone: "warn", when: "Since then", title: "Google Cloud and Slack", text: "Both got as far as the console and turned up more bugs, now fixed (decisions 91 to 98). No credential from either yet." },
];

// Who does each step. "agent" = CredAgent (model and code), "you" = a person.
const GRID = [
  ["Research the app and write the plan", "agent", ""],
  ["Give the go-ahead (each session)", "you", ""],
  ["Sign in: password, codes, 2FA", "you", ""],
  ["CAPTCHA or bot check", "you", ""],
  ["Fill in the app name, callback URL and other fields", "agent", "approved values only"],
  ["Accept the provider's terms and click Create", "you", "always you"],
  ["Choose an app type or a permission", "you", "your call"],
  ["Reset a secret (the old one stops working)", "you", "your call"],
  ["Copy the credential off the page", "agent", "plain code, not the AI"],
  ["Run the live test", "agent", ""],
  ["Delete the apps it created", "you", "the agent never deletes anything"],
];

const BUILD = [
  "I scrapped the first design and chose the simpler agent loop (decision 78).",
  "I decided where secrets live (files only I can read, outside the project) and the default callback address (decision 53).",
  "I decided that accepting terms is always a person's job, and that when a provider's terms are unclear, it can run only with my consent each session (decisions 48 to 50 and 59).",
  "I picked which providers to try, when to stop and when to abandon a run, and I said yes before every real-provider run.",
  "For this web page I chose a small local server, plain JavaScript, the name “CredAgent”, confirmations inside the page, and a simpler home screen.",
  "Running it on real apps is what found the problems. I noticed Google offering an API-key screen when I'd asked for OAuth (decision 96), and a run going in circles (decision 97).",
];

// Real-provider runs from RESULTS.md, in order. Colour is backed by a word.
const RUNS = [
  ["1", "Spotify", "Stopped", "plain"], ["2", "Discord", "Blocked", "warn"], ["3", "Discord", "Abandoned", "plain"],
  ["4", "Discord", "Out of steps", "bad"], ["5", "Discord", "Stalled", "warn"], ["6", "Discord", "Blocked", "warn"],
  ["7", "Discord", "Verified", "ok"],
];

function story() {
  return h("ol", { class: "story" }, STORY.map((s) =>
    h("li", { class: `story-item st-${s.tone}` },
      h("span", { class: "story-when" }, s.when), h("strong", {}, s.title), h("span", {}, s.text))));
}

function grid() {
  return h("div", { class: "grid", role: "table", "aria-label": "Who does each step" },
    h("div", { class: "grid-row grid-head", role: "row" },
      h("span", { role: "columnheader" }, "Step"), h("span", { role: "columnheader" }, "CredAgent"), h("span", { role: "columnheader" }, "You")),
    GRID.map(([step, by, note]) => h("div", { class: "grid-row", role: "row" },
      h("span", { class: "grid-step", role: "cell" }, step, note && h("small", {}, note)),
      h("span", { class: `grid-cell ${by === "agent" ? "on-agent" : ""}`, role: "cell" },
        by === "agent" ? h("span", { class: "mark", "aria-label": "CredAgent does this" }, "●") : h("span", { class: "sr" }, "no")),
      h("span", { class: `grid-cell ${by === "you" ? "on-you" : ""}`, role: "cell" },
        by === "you" ? h("span", { class: "mark", "aria-label": "You do this" }, "●") : h("span", { class: "sr" }, "no")))));
}

function layers() {
  const layer = (n, title, text) => h("li", { class: "layer" }, h("span", { class: "layer-n", "aria-hidden": "true" }, n),
    h("div", {}, h("strong", {}, title), h("p", {}, text)));
  return h("ol", { class: "layers" },
    layer("1", "Does the credential actually work?",
      "On Discord (run 7), a real token request with the new credential came back with HTTP 200 and an access token. Only a passing test can end a run as a success."),
    layer("2", "Automated tests",
      "About 380 of them. Many drive a real Chrome window against a pretend provider that I can script: a clean run, a blocked one, a page that tries to trick the agent, terms, CAPTCHAs, cookie banners, a broken model, an outage."),
    layer("3", "The real model, on a pretend provider",
      "52 runs against the pretend provider (13 situations, run twice, with two models). All 52 succeeded and no safety check failed. A run took about 8 model calls. That's a test bench, not a real provider, so I don't count it as proof for real consoles."),
    layer("4", "Nothing leaked",
      "Tests comb through every saved file and all the terminal output looking for a leaked secret, and every commit is scanned for secrets too."),
    layer("5", "An honest paper trail",
      "Every real run goes in RESULTS.md with how it ended, failures included, and every decision is written down in docs/DECISIONS.md."));
}

function runStrip() {
  return h("div", { class: "runs" },
    h("ol", { class: "run-strip" }, RUNS.map(([n, app, outcome, tone]) =>
      h("li", { class: `run-chip rc-${tone}` }, h("span", { class: "run-n" }, `#${n}`), h("strong", {}, outcome), h("span", { class: "run-app" }, app)))),
    h("p", { class: "muted small" }, "The first seven runs on real providers, as written down in RESULTS.md. The Google Cloud and Slack attempts came after these."));
}

export function renderApproach({ home }) {
  return page("My approach",
    "How I went about building it, the places a person still has to step in, and how I checked that it works.",
    section("The approach in short", null,
      cards(PRINCIPLES, "four"),
      callout("Everything's written down", "I worked in sprints and kept a log. Every decision that mattered is in it (98 so far, each with its evidence), and so is every real run, the failures included.")),
    section("How the design changed", "My first design didn't survive contact with real developer consoles. Here's the short version of what happened. The long version is in the decision log.", story()),
    section("Where human involvement was needed", "There are two kinds. The people stepping in during a run, and the calls I made while building it."),
    h("h3", { class: "doc-h3" }, "During a run"),
    grid(),
    h("h3", { class: "doc-h3" }, "While building it"),
    list(BUILD),
    section("How the results were verified", "Five layers, starting with the strongest evidence.",
      stats([
        { label: "Real credentials verified", value: "1", note: "Discord" },
        { label: "Automated tests", value: "~380" },
        { label: "Measured model runs", value: "52", note: "52 succeeded" },
        { label: "Decisions recorded", value: "98" },
      ]),
      layers(),
      runStrip()),
    section("What I can't claim yet", null,
      list([
        "Only one real provider, Discord, has a credential I've verified. Other providers, API keys and the authorization-code flow haven't been tested.",
        "I've only tested it on a Mac, with Google Chrome.",
        "The model isn't predictable, so two runs on the same app can differ. For example, it may or may not fill in an optional field.",
        "It never deletes the apps it creates, so you'll want to tidy those up in the provider's console.",
      ])),
    cta(home));
}
