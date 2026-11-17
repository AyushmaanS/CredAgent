import { h } from "../dom.js";
import { page, section, cards, list, stats, cta } from "./parts.js";

const IDEAS = [
  { tag: "1", title: "Research first", text: "Read the provider's docs and make a plan before opening a browser." },
  { tag: "2", title: "The AI suggests, code decides", text: "Safety rules live in plain code, so the AI can't talk its way past them." },
  { tag: "3", title: "People do their own steps", text: "Signing in, codes, CAPTCHAs and terms are never done for you." },
];

// What actually happened, from RESULTS.md and the decision log.
const STORY = [
  { tone: "bad", when: "First try", title: "It didn't work on real sites", text: "My first design fell over on Discord's real pages. It took five runs to find out why, and I gave up on one of them." },
  { tone: "plain", when: "Second try", title: "I started over, simpler", text: "One AI step at a time, with plain code around it for the rules." },
  { tone: "ok", when: "Discord, run 7", title: "A real credential", text: "It got the credential from Discord and proved it works with a real request." },
  { tone: "warn", when: "Since then", title: "Google Cloud and Slack", text: "Both got as far as the console and hit more bugs, which I fixed. Neither has produced a credential yet." },
];

// Who does each step. "agent" = CredAgent, "you" = a person.
const GRID = [
  ["Research the app and make a plan", "agent", ""],
  ["Say go, each session", "you", ""],
  ["Sign in, enter codes, solve CAPTCHAs", "you", ""],
  ["Fill in the app name and other fields", "agent", ""],
  ["Accept the terms and click Create", "you", "always you"],
  ["Choose an app type or permission, reset a secret", "you", "your call"],
  ["Copy the credential off the page", "agent", ""],
  ["Test that it works", "agent", ""],
  ["Delete the app afterwards", "you", "it never deletes"],
];

const BUILD = [
  "I threw out the first design and chose the simpler loop.",
  "I decided where secrets are kept, and that a person always accepts terms.",
  "I picked the providers to try, and I said yes before every real run.",
  "Running it on real apps found the problems. I spotted things like Google offering an API-key screen when I wanted OAuth, and a run going in circles.",
];

// The real-provider runs recorded in RESULTS.md. Colour is backed by a word.
const RUNS = [
  ["1", "Spotify", "Stopped", "plain"], ["2", "Discord", "Blocked", "warn"], ["3", "Discord", "Abandoned", "plain"],
  ["4", "Discord", "Out of steps", "bad"], ["5", "Discord", "Stalled", "warn"], ["6", "Discord", "Blocked", "warn"],
  ["7", "Discord", "Worked", "ok"],
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
      "On Discord (run 7) I made a real request with the new credential and got an access token back. A run only counts as a success if a test like that passes."),
    layer("2", "A fake developer site for testing",
      "I built a small fake console that runs on this computer, with settings for sign-in, terms, CAPTCHAs, tricky pages and failures. About 380 automated tests run against it, many in a real Chrome window."),
    layer("3", "Writing everything down",
      "Every real run is in RESULTS.md, failures included, and every decision is in the decision log. Tests and a scan also check that no secret leaks into files or output."));
}

function runStrip() {
  return h("div", { class: "runs" },
    h("ol", { class: "run-strip" }, RUNS.map(([n, app, outcome, tone]) =>
      h("li", { class: `run-chip rc-${tone}` }, h("span", { class: "run-n" }, `#${n}`), h("strong", {}, outcome), h("span", { class: "run-app" }, app)))),
    h("p", { class: "muted small" }, "The first seven runs on real providers, as written in RESULTS.md. The Google Cloud and Slack attempts came after these."));
}

export function renderApproach({ home }) {
  return page("My approach",
    "How I built it, where people still step in, and how I checked it works.",
    section("The idea", "You give it an app name. It works out how that app hands out credentials, does the clicking for you, and stops whenever a step is really yours.",
      cards(IDEAS)),
    section("How it went", "It took longer than I expected. Real developer sites are messier than I thought.", story()),
    section("Where people step in", "Some steps are meant for a person. Here is who does what.",
      grid(),
      h("h3", { class: "doc-h3" }, "My own calls while building it"),
      list(BUILD)),
    section("How I checked it", null,
      stats([
        { label: "Real credentials proven", value: "1", note: "Discord" },
        { label: "Automated tests", value: "~380" },
        { label: "Decisions written down", value: "98" },
      ]),
      layers(),
      runStrip()),
    section("What I can't claim yet", null,
      list([
        "Only Discord has produced a credential I've proven. Other providers and credential types are untested.",
        "I've only tried it on a Mac, with Chrome.",
        "The AI isn't predictable, so two runs on the same app can differ.",
        "It never deletes the apps it creates. You'll want to tidy those up yourself.",
      ])),
    cta(home));
}
