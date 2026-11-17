import { h } from "../dom.js";
import { page, section, journey, loop, cards, callout, cta, who } from "./parts.js";

const JOURNEY = [
  { title: "You name an app", who: ["you"],
    text: "That's the only thing you type. GitHub, Slack, Google Cloud, whatever you need access to." },
  { title: "It does its homework", who: ["model", "code"],
    text: "CredAgent searches the web and reads the provider's own docs, then an AI model drafts a plan: which kind of credential to get, where the developer console lives, what the steps are. The model can be wrong, so plain code checks its work before the plan is kept. A source it cites has to be one we actually fetched, a quote has to really appear on that page, and the console address has to sit on the provider's own domain." },
  { title: "You say go", who: ["you"],
    text: "Before anything opens, you see what it's about to do: which credential, which sites it may visit, and what the provider's terms say (or that nobody checked). You tell it which account you're using and confirm. For a real provider it asks again every session." },
  { title: "It works the console", who: ["model", "code", "you"],
    text: "A Chrome window opens, and you can watch it the whole time. The agent clicks through the provider's console one small step at a time (see the loop below). Anything that's really yours to do, like signing in, typing a code, solving a CAPTCHA or accepting terms, it hands to you and waits." },
  { title: "It copies the credential", who: ["code"],
    text: "Once the credential is on screen, ordinary code lifts it off the page. The AI never sees it. It's saved to a file only you can read, outside the project folder, and shown masked here until you choose to reveal it." },
  { title: "It checks that it works", who: ["code"],
    text: "Finally it makes a real request with the new credential. If that fails, the run doesn't count as a success, however good it looked. You get a report of what happened, what you did, and what wasn't tested." },
];

const LOOP = [
  { title: "Look", by: "code", text: "Reads the page as a numbered list of things you could click or fill. Secrets are left out." },
  { title: "Safety checks", by: "code", text: "Spots a CAPTCHA, a payment form, a terms box or a page it shouldn't be on, and stops or hands over before the AI is even asked." },
  { title: "Pick one move", by: "model", text: "The model chooses a single action by its number and says why. Or it asks you." },
  { title: "Sanity check", by: "code", text: "Is that element really there? Is the text it wants to type one of the approved values?" },
  { title: "Rules and risk", by: "code", text: "Gives the move a ruling, from the next section, and a risk level." },
  { title: "Do it, write it down", by: "code", text: "The browser performs the action, and the result is saved to disk." },
];

function verdicts() {
  const row = (cls, name, line, eg) => h("li", { class: `verdict v-${cls}` },
    h("strong", {}, name), h("span", {}, line), h("em", {}, eg));
  return h("div", { class: "verdicts" },
    h("div", { class: "verdict-in" }, "The model suggests a move"),
    h("div", { class: "verdict-arrow", "aria-hidden": "true" }, "↓"),
    h("ol", { class: "verdict-row" },
      row("allow", "Go ahead", "It just happens.", "Open a page, type the app name"),
      row("deny", "Never", "No matter what anyone says.", "Delete something, pay, publish, leave the approved sites"),
      row("do", "Over to you", "The agent waits for you to do it.", "Sign in, accept terms, solve a CAPTCHA"),
      row("decide", "Your call", "It asks, then follows your answer.", "An app type, a permission, resetting a secret")));
}

function roles() {
  const col = (kind, verb, did, never) => h("div", { class: `role role-${kind}` },
    h("div", { class: "role-head" }, who(kind), h("strong", {}, verb)),
    h("ul", {}, did.map((t) => h("li", {}, t))),
    never && h("p", { class: "role-never" }, never));
  return h("div", { class: "roles" },
    col("model", "Suggests", [
      "Reads the text on the page",
      "Picks one move at a time and explains it",
      "Asks you when it isn't sure",
    ], "It never sees screenshots, credentials, or what's typed into a field. It can only type values that were approved ahead of time."),
    col("code", "Decides", [
      "The hard stops: payments, deleting, publishing, other sites, identity checks",
      "A ruling and a risk level for every move",
      "One app per run, copying the credential, the live test, saving progress",
    ], "Nothing the model says can lift a hard stop."),
    col("you", "Does and chooses", [
      "Signing in, email codes, 2FA, CAPTCHAs",
      "Accepting terms. Always you.",
      "The real choices: app type, permissions, resetting a secret",
    ], "And you give the go-ahead at the start of each session."));
}

function outcomes() {
  const item = (cls, name, text) => h("li", { class: `outcome o-${cls}` }, h("strong", {}, name), h("span", {}, text));
  return h("ul", { class: "outcomes" },
    item("ok", "Succeeded", "The credential was copied and the live test passed."),
    item("warn", "Partial", "It works, but the test could only go so far. For example, the app is still in test mode."),
    item("block", "Blocked", "Something can't be done right now, like an identity check. The report says what to do next."),
    item("bad", "Failed or stopped", "Something broke, or you stopped it. Your progress is saved, and you can usually pick up where it left off."));
}

export function renderHowItWorks({ home }) {
  return page("How it works",
    "Give CredAgent an app name and it gets you a working credential. It runs on your computer in a Chrome window you can watch, and whenever a step is really yours, it stops and asks.",
    section("From a name to a tested credential", "Six stages. The little tags show who's doing the work at each one.",
      journey(JOURNEY)),
    section("The loop at the heart of it", "Stage four is a loop. Each turn is one small step, and nearly all of it is ordinary code. The AI only picks the move.",
      loop(LOOP, "Round and round until the credential shows up, something blocks it, or it runs out of steps (60)."),
      callout("Why so small?", "Every move is checked and saved before the next. If the app crashes or you stop it, nothing is lost. And if a click might not have gone through, it looks again instead of clicking twice.")),
    section("Who does what", "An AI model is good at reading a messy page and not good enough to be trusted with the keys. So it suggests, and everything else is decided elsewhere.", roles()),
    section("Every move gets a ruling", "Before the browser does anything, code sorts the move into one of four bins. If it can't tell how risky something is, it treats it as riskier.", verdicts()),
    section("When it hands over to you",
      "You'll see a card that says “Your attention is needed”, with what to do and where.",
      cards([
        { tag: "Over to you", title: "Do it, then press “I did it”", text: "The agent looks at the page again. If nothing changed, it tells you so instead of assuming." },
        { tag: "Your call", title: "Pick an option", text: "Your answer is saved, and the agent carries on from there." },
        { tag: "Whenever", title: "Save and stop", text: "Everything is kept exactly where you left it. Pick it up later from this page or the terminal." },
      ])),
    section("Where your credentials go", null,
      cards([
        { title: "Not in the project", text: "They live in files only you can read, somewhere else on this computer." },
        { title: "Hidden until you ask", text: "You see the first few characters and a length. Reveal hides itself again after 30 seconds." },
        { title: "Kept from the AI", text: "Secrets are masked before anything goes to a model, and the model can't see the credential on the page anyway." },
        { title: "Only on this machine", text: "This page answers only to 127.0.0.1, and only with the one-time link from your terminal." },
      ], "four")),
    section("How a run can end", "Only a passing live test counts as success. Everything else is reported honestly, for what it is.", outcomes()),
    cta(home));
}
