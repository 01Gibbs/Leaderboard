// The walkthrough's content: one entry per step. Edit the words here; tour.js only displays them.
//
// Each step has a chapter, a title and text (HTML), and shows either
//   target: a data-tour name in index.html (or a list: the first one visible is used), highlighted on the live leaderboard, or
//   stage:  HTML shown in place of the leaderboard (diagrams, tables, links).
// `ctx` is built from this repository by walkthrough.py (GitHub links, forms, lessons, recent actions).
// Points come from RULES in ../scoring.js, the same rules the leaderboard and the grader use.

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const link = (url, text) => (url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));

const LEVELS = {
  none: { label: 'Marked by a facilitator', setup: 'about 5 minutes', during: 'a facilitator marks each person (about a minute each)' },
  build: { label: 'Builds', setup: 'about 5 minutes', during: 'automatic' },
  tests: { label: 'Our tests pass', setup: '30 to 60 minutes, plus test files and a reference solution', during: 'automatic' },
  custom: { label: 'Custom check', setup: '2 to 4 hours, mostly done by Claude', during: 'automatic, with reasons' },
};
const levelOf = (check) => LEVELS[check] || LEVELS.custom;

// The facilitator forms, in the order shown. Any other workflow is for maintainers and is not listed.
const FORM_HELP = {
  'facilitator-award.yml': 'Points for helping a colleague, stretch tasks, or bonus points. A minus sign takes them away.',
  'facilitator-mark.yml': 'Mark an exercise Correct that you checked by hand.',
  'facilitator-rename.yml': 'Show someone’s real name instead of their GitHub username.',
  'facilitator-merge.yml': 'Someone appears twice: keep one row. The higher value of every column is kept.',
  'facilitator-add.yml': 'Add someone who has not opened a pull request yet.',
  'facilitator-undo.yml': 'Reverse the latest change. Run it again to go back further.',
  'grade.yml': 'Grade new pull requests now instead of waiting for the next 30-minute run.',
};

function fileLink(ctx, path, text) {
  return link(ctx.repo && `${ctx.repo.url}/blob/main/${path}`, text || path);
}

export function steps(ctx) {
  const pts = RULES.points; // a top-level const in ../scoring.js: visible here, but not as globalThis.RULES
  const example = ctx.lessons[0];
  const facilitatorForms = Object.keys(FORM_HELP).map((file) => ctx.forms.find((f) => f.file === file)).filter(Boolean);
  const actionsUrl = ctx.repo && `${ctx.repo.url}/actions`;

  return [
    // ---------- 1. The leaderboard ----------
    {
      chapter: 'The leaderboard',
      title: 'Welcome',
      stage: `
        <h2>Java Exercise Leaderboard</h2>
        <p class="lead">A five-minute tour of the leaderboard: what people see, how scores get there, and where you change them.</p>
        <div class="cards">
          <div class="card"><b>Facilitators</b><span>where to give points, fix names and undo mistakes</span></div>
          <div class="card"><b>Project leads</b><span>how it works and what a new workshop repo needs</span></div>
          <div class="card"><b>Maintainers</b><span>where each part lives</span></div>
        </div>
        <p class="hint">Use <kbd>→</kbd> and <kbd>←</kbd> or the buttons. Links open in a new tab.</p>`,
      text: (ctx.sample
        ? '<p>The board in this tour shows <b>made-up example people</b>, so you can see every state. To see the real scores, run <code>python3 walkthrough.py --real</code>.</p>'
        : '<p>The board in this tour shows the <b>real scores</b> from this folder.</p>')
        + (ctx.repo ? `<p>The public leaderboard is at ${link(ctx.repo.pages_url, ctx.repo.pages_url)}.</p>` : ''),
    },
    {
      chapter: 'The leaderboard',
      title: 'Totals',
      target: 'stats',
      text: '<p>People on the board, pull requests submitted, and how many of them are correct.</p>',
    },
    {
      chapter: 'The leaderboard',
      title: 'How points work',
      target: 'rubric',
      text: `<p>Each exercise is worth <b>${pts.submitted}</b> when submitted and <b>${pts.correct}</b> when correct. Facilitators add <b>+${pts.stretch}</b> per stretch task, <b>+${pts.helped}</b> per time someone helped a colleague, and any bonus points.</p>
        <p>These numbers live in one file, <code>scoring.js</code>, which the page and the grader both read.</p>`,
    },
    {
      chapter: 'The leaderboard',
      title: 'One column per exercise',
      target: ['columns', 'first-row'], // the header row is hidden on narrow screens
      text: `<p>One column per exercise (${ctx.lessons.map((l) => esc(l.label)).join(', ')}), then the points facilitators give, then the total.</p><p>Adding a workshop repo adds a column here by itself.</p>`,
    },
    {
      chapter: 'The leaderboard',
      title: 'Exercise results',
      target: 'first-row-results',
      text: `<p><b>Not yet</b>: no pull request.<br><b>Submitted</b>: they opened a pull request on the exercise repo.<br><b>Correct</b>: the automatic check passed, or a facilitator marked it.</p>
        <p>New people appear by themselves when they open their first pull request.</p>`,
    },
    {
      chapter: 'The leaderboard',
      title: 'Points from facilitators',
      target: 'first-row-extras',
      text: '<p>Stretch tasks, help given and bonus points. Only facilitators change these, with the <b>Award points</b> form (later in this tour).</p>',
    },
    {
      chapter: 'The leaderboard',
      title: 'Find, filter, share',
      target: 'tools',
      text: '<p>Search by name, show only people with a correct solution, or copy the whole board as text to paste into a chat.</p>',
    },
    {
      chapter: 'The leaderboard',
      title: 'Recognition',
      target: 'recognition',
      text: '<p>Picked out automatically: correct on every exercise, most stretch tasks, most help given.</p>',
    },

    // ---------- 2. How it works ----------
    {
      chapter: 'How it works',
      title: 'From pull request to points',
      stage: `
        <h2>From pull request to points</h2>
        <ol class="flow">
          <li><b>A participant opens a pull request</b><span>on the exercise repo, from their fork</span></li>
          <li><b>Every 30 minutes the grader runs</b><span>on GitHub, not on anyone’s computer: it finds new pull requests and checks each one</span></li>
          <li><b>Scores are saved</b><span>in participants.csv, one row per person</span></li>
          <li><b>The page updates</b><span>a minute or two later</span></li>
        </ol>
        <h3>And separately, facilitators</h3>
        <ol class="flow side">
          <li><b>A facilitator fills in a form</b><span>in the Actions tab on GitHub: points, names, merges, undo</span></li>
          <li><b>The same file is updated</b><span>and the page follows</span></li>
        </ol>`,
      text: '<p>Two things change scores: the automatic grader, and facilitators. Both write to one file, and the page reads it.</p><p>The grader only ever raises a result, so it never overwrites a facilitator’s change.</p>',
    },
    {
      chapter: 'How it works',
      title: 'Where things live',
      stage: `
        <h2>Where things live</h2>
        <table>
          <tr><th>${fileLink(ctx, 'participants.csv')}</th><td>Everyone’s scores. The page reads this.</td></tr>
          <tr><th>${fileLink(ctx, 'lessons.json')}</th><td>The exercises: name, repo, and how each is checked.</td></tr>
          <tr><th>${fileLink(ctx, 'grader/results.json')}</th><td>Why each pull request passed or failed.</td></tr>
          <tr><th>${ctx.recent_actions.length ? fileLink(ctx, 'grader/history.json') : 'grader/history.json'}</th><td>Every facilitator change: who, when, what. Undo uses this. It appears after the first change.</td></tr>
          <tr><th>${fileLink(ctx, 'FACILITATOR.md')}</th><td>One-page guide for facilitators.</td></tr>
          <tr><th>${fileLink(ctx, 'README.md')}</th><td>Setup and how it works, for the project lead.</td></tr>
          <tr><th>${fileLink(ctx, 'grader/checks.py', 'grader/')}</th><td>The grader and its tests, for maintainers.</td></tr>
        </table>`,
      text: '<p>Everything is in this one repository. Nothing needs installing to use it.</p>',
    },

    {
      chapter: 'How it works',
      title: 'Before the first workshop',
      stage: `
        <h2>Before the first workshop</h2>
        <p>Done once, by whoever owns the repository${ctx.repo ? ` (${link(ctx.repo.url + '/settings', 'Settings')})` : ''}:</p>
        <ol class="flow">
          <li><b>Publish the page</b><span>Settings \u2192 Pages \u2192 Source: GitHub Actions</span></li>
          <li><b>Let the forms save changes</b><span>Settings \u2192 Actions \u2192 General \u2192 Workflow permissions: Read and write</span></li>
          <li><b>Add facilitators</b><span>Settings \u2192 Collaborators, with Write access</span></li>
          <li><b>Grade once</b><span>Actions \u2192 Grade submissions \u2192 Run workflow (the first run takes 20 to 40 minutes)</span></li>
        </ol>`,
      text: `<p>After that, everything runs by itself. Details are in ${fileLink(ctx, 'README.md')}.</p>`,
    },

    // ---------- 3. For facilitators ----------
    {
      chapter: 'For facilitators',
      title: 'The forms',
      stage: `
        <h2>Facilitator forms</h2>
        <p>On GitHub: ${link(actionsUrl, 'the Actions tab')} → pick a form on the left → <b>Run workflow</b>.</p>
        <table>${facilitatorForms.map((f) => `<tr><th>${link(f.url, f.name.replace(/^Facilitator: /, ''))}</th><td>${esc(FORM_HELP[f.file])}</td></tr>`).join('')}</table>`,
      text: '<p>Everything a facilitator does is one of these forms. You need <b>Write</b> access to the repository to run them.</p><p>For a person, type their name as on the board or their GitHub username. If nobody matches, nothing changes and it suggests close names.</p>',
    },
    {
      chapter: 'For facilitators',
      title: 'After you run a form',
      stage: `
        <h2>After you run a form</h2>
        <ol class="flow">
          <li><b>About 30 seconds later the run shows ✅ or ❌</b><span>click it for a one-line summary of what changed</span></li>
          <li><b>❌ means nothing changed</b><span>the summary says why, e.g. a misspelled name</span></li>
          <li><b>The page updates a minute or two later</b><span>for everyone</span></li>
        </ol>
        <h3>Recent changes</h3>
        ${ctx.recent_actions.length
          ? `<ul class="plain">${ctx.recent_actions.map((h) => `<li><b>${esc(h.by)}</b>: ${esc(h.action)} <small>${esc(h.at)}</small></li>`).join('')}</ul>`
          : '<p class="muted">No facilitator changes yet.</p>'}`,
      text: '<p><b>Undo</b> reverses only what the last change touched, and keeps anything changed since. Two facilitators saving at the same moment is fine: both changes land.</p>',
    },
    {
      chapter: 'For facilitators',
      title: 'Common questions',
      stage: `
        <h2>Common questions</h2>
        <dl>
          <dt>Someone shows up under a GitHub username</dt><dd><b>Rename a person</b>. The username stays linked, so their pull requests keep counting.</dd>
          <dt>Someone appears twice</dt><dd><b>Merge duplicate people</b>. Nobody loses points: the higher value of every column is kept.</dd>
          <dt>Why isn’t a submission Correct yet?</dt><dd>Open ${fileLink(ctx, 'grader/results.json')} and search for their GitHub username: each pull request lists its reasons. Grading runs every 30 minutes, or now with <b>Grade submissions</b>.</dd>
          <dt>I made a mistake</dt><dd><b>Undo last change</b>.</dd>
        </dl>`,
      text: `<p>The full guide is ${fileLink(ctx, 'FACILITATOR.md')}.</p>`,
    },

    // ---------- 4. Workshop repos ----------
    {
      chapter: 'Workshop repos',
      title: 'The exercises today',
      stage: `
        <h2>The exercises today</h2>
        <table class="grid">
          <tr><th>Exercise</th><th>Repo</th><th>How “Correct” is decided</th><th>People</th><th>Correct</th></tr>
          ${ctx.lessons.map((l) => `<tr><td>${esc(l.label)}</td><td>${link(l.repo_url, l.repo)}</td><td>${levelOf(l.check).label}</td><td>${l.people}</td><td>${l.correct}</td></tr>`).join('')}
        </table>`,
      text: `<p>Each exercise is one entry in ${fileLink(ctx, 'lessons.json')}: its name, its repo, and how it is checked.</p><p>Counts come from the latest grading results in this folder.</p>`,
    },
    {
      chapter: 'Workshop repos',
      title: 'lessons.json: the list of exercises',
      stage: `
        <h2>lessons.json: the list of exercises</h2>
        <p>One entry per exercise. ${ctx.lessons.length ? 'The first one, field by field:' : ''}</p>
        ${example ? `
        <pre class="code">{
  <span class="k">"key"</span>: "${esc(example.key)}",
  <span class="k">"label"</span>: "${esc(example.label)}",
  <span class="k">"repo"</span>: "${esc(example.repo)}",
  <span class="k">"check"</span>: "${esc(example.check)}"
}</pre>
        <table>
          <tr><th>key</th><td>The column in participants.csv. Lowercase letters, digits and _; never change it once people have results.</td></tr>
          <tr><th>label</th><td>The column heading on the leaderboard. Safe to change any time.</td></tr>
          <tr><th>repo</th><td>Where participants open their pull requests: ${link(example.repo_url, example.repo)}.</td></tr>
          <tr><th>check</th><td>How \u201cCorrect\u201d is decided: <b>none</b> (a facilitator marks it), <b>build</b>, <b>tests</b> (our test files in grader/fixtures/&lt;key&gt;/), or a custom check written in grader/checks.py.</td></tr>
        </table>` : ''}
        ${ctx.lesson_problems.length ? `<h3>lessons.json has problems right now</h3><ul class="checks">${ctx.lesson_problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>
          <p class="hint">Until they are fixed, grading and facilitator forms stop with this message, and nothing is changed.</p>` : ''}
        <h3>Adding an exercise</h3>
        <ol class="flow">
          <li><b>Add one entry</b><span>with <code>"check": "none"</code> to start</span></li>
          <li><b>A column appears</b><span>on the leaderboard and in participants.csv</span></li>
          <li><b>Pull requests count</b><span>as Submitted within 30 minutes</span></li>
          <li><b>Raise the level later</b><span>if automating it is worth it</span></li>
        </ol>`,
      text: `<p>${fileLink(ctx, 'lessons.json')} is the one place a workshop repo is connected to the leaderboard: the page, the grader, the facilitator forms and this tour all read it.</p>
        <p>A mistake in it (a typo in a key, a missing label) is reported by name, and nothing is changed until it is fixed.</p>`,
    },
    {
      chapter: 'Workshop repos',
      title: 'What a workshop repo needs',
      stage: `
        <h2>What a workshop repo needs</h2>
        <ul class="checks">
          <li>A <b>public</b> GitHub repo (so the grader can read its pull requests) with the starter project and instructions for participants, such as a PROBLEM_STATEMENT.md.</li>
          <li>Participants <b>fork it and open a pull request</b> with their work. Pull requests are never merged; ask participants to <b>leave theirs open</b>, because closing one without merging withdraws the submission.</li>
          <li><b>Nothing else in the repo</b>: no workflows, secrets or settings. The leaderboard does the rest.</li>
        </ul>
        <h3>How much work to add one</h3>
        <table class="grid">
          <tr><th>How “Correct” is decided</th><th>Setup</th><th>During the workshop</th></tr>
          ${Object.values(LEVELS).map((l) => `<tr><td>${l.label}</td><td>${l.setup}</td><td>${l.during}</td></tr>`).join('')}
        </table>
        <p class="hint">Estimates, not measurements: nothing has been timed on a real workshop yet.</p>`,
      text: `<p>For a two-day workshop, start with <b>marked by a facilitator</b> and automate later if it is worth it.</p>
        <p>To add one, ask Claude Code in this repo to <i>“add the lesson in owner/repo to the leaderboard”</i>. Its add-lesson skill walks through it.</p>
        <p>The grader does not read PROBLEM_STATEMENT.md today. A planned improvement would draft the checks from it (an estimated 30–45 minutes per lesson): ${fileLink(ctx, 'docs/research/adding-lessons.md', 'the research')}.</p>`,
    },
    {
      chapter: 'Workshop repos',
      title: 'That’s it',
      stage: `
        <h2>That’s it</h2>
        <div class="cards">
          <div class="card"><b>Facilitators</b><span>keep ${fileLink(ctx, 'FACILITATOR.md')} open during the workshop</span></div>
          <div class="card"><b>Project leads</b><span>one-time setup is in ${fileLink(ctx, 'README.md')}</span></div>
          <div class="card"><b>Maintainers</b><span>run <code>python3 -m unittest discover grader/tests</code></span></div>
        </div>
        <p class="hint">Close this tab and press <kbd>Ctrl</kbd>+<kbd>C</kbd> in the terminal to stop.</p>`,
      text: '<p>Run <code>python3 walkthrough.py</code> again any time.</p>',
    },
  ];
}
