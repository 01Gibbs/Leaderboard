# Java Exercise Leaderboard

A public leaderboard for the workshop. Participants submit each exercise as a pull request; the leaderboard picks them up, grades them, and ranks everyone by points. Facilitators adjust scores from GitHub's **Actions** tab, with nothing to install.

**New here? Start with the walkthrough.** In this folder, run `python3 walkthrough.py` (Windows: `py walkthrough.py`; Python 3.8 or newer). It opens a five-minute guided tour of the leaderboard in your browser: what people see, how scores get there, the facilitator forms, and what a workshop repo needs. It only runs on your computer; press Ctrl+C to stop.

- **Facilitators:** everything you need is in [FACILITATOR.md](FACILITATOR.md).
- **Project lead:** set it up once (below), then add lessons as the workshop grows.

## How it works

```
participant opens a PR ──► "Grade submissions" (every 30 min) ──► participants.csv ──► public page
                                                                        ▲
facilitator fills in a form in the Actions tab (award, merge, undo...) ─┘
```

1. **Submissions.** Every 30 minutes, the *Grade submissions* workflow lists the pull requests on each lesson's repository (listed in [`lessons.json`](lessons.json)). Each author is a participant: anyone new gets a row, named from their GitHub profile, and the exercise shows as *Submitted*.
2. **Grading.** Each pull request's latest commit is checked once, with the grader's own tests (so editing the tests in a pull request does not help). If it passes, the exercise shows as *Correct*. The reason for every pass or fail is kept in `grader/results.json`.
3. **Facilitator changes** (points, names, merges, undo) are forms in the Actions tab. Each one logs exactly which cells it changed in `grader/history.json`, so undo can change exactly those back. Changes made at the same moment all land: each run applies its change to the latest version and retries if someone else saved first.
4. **The page** (`index.html`, served by GitHub Pages) reads `participants.csv` and `lessons.json`, and updates a minute or two after any change.

The grader never lowers a result, so a facilitator's changes are never overwritten by the next grading run.

## Points
Submitted **10**, correct **30**, each stretch task **+5**, each time helping a colleague **+5**, plus any bonus points a facilitator gives. They live in one place, the `RULES` block at the top of `scoring.js`, which the page and the grader both read.

## One-time setup (repository owner)
1. **Publish the page:** Settings → Pages → *Source* → **GitHub Actions**. The *Publish the page* workflow deploys it after every change. The site appears at `https://<owner>.github.io/<repository>/`.
2. **Allow the workflows to save changes:** Settings → Actions → General → *Workflow permissions* → **Read and write permissions** → Save. If `main` has branch protection, allow GitHub Actions to push to it.
3. **Give facilitators access:** Settings → Collaborators → add each facilitator with **Write** access. That is what lets them run the forms.
4. **Run it once:** Actions → *Grade submissions* → **Run workflow**. The first run builds every existing submission and takes 20 to 40 minutes. After that, it runs by itself and only grades new commits.

The page, `participants.csv` and the grading reasons are public: anyone with the link can see every name and score.

## Lessons
Each lesson is one entry in `lessons.json`:

```json
{ "key": "framework_upgrade", "label": "Framework upgrade", "repo": "AtulKumarSharma79/Frameworkupgrade", "check": "framework_upgrade" }
```

`key` becomes the CSV column, `label` is shown on the page, `repo` is where participants open pull requests. `check` sets how much is automated:

| `check` | An exercise is *Correct* when | Extra work |
|---|---|---|
| `none` | a facilitator marks it | none |
| `build` | the submission builds | none |
| `tests` | our tests pass against it | put test files in `grader/fixtures/<key>/`, mirroring the project's paths |
| a custom name | anything a script can check | a function in `grader/checks.py` |

The current custom checks:
- **FizzBuzz:** the participant's tests must pass against the real `FizzBuzz` and catch 7 deliberately broken versions.
- **REST API:** starts the app and calls `GET`/`POST /api/employees`, including the `400` cases.
- **Framework upgrade:** checks for Spring Boot 3.5.x, no `javax.*` imports, the removed properties gone, and `commons-text` 1.10 or newer. The original tests must pass, and the API must behave as before.
- **Container image:** requires an approved, pinned `eclipse-temurin` 21/25 image, a multi-stage build with a JRE runtime, a non-root user and a `.dockerignore`. It then builds and runs the image and calls the API.

**Adding a lesson with Claude:** in this repository, ask Claude Code to *"add the lesson in owner/repo to the leaderboard"*. The `add-lesson` skill (`.claude/skills/add-lesson`) walks through choosing the level, writing and testing the check, and recording existing submissions. To add one by hand, add the entry to `lessons.json` with `"check": "none"`, then raise the level later.

## For maintainers
- **Code:** Python 3 standard library only, in `grader/`, plus `scoring.js` at the top:
  - `scoring.js`: the rules (points, status words, how the CSV is read). The page loads it, and `grader/rules.py` reads the same rules, so the two can't disagree; a test runs both on tricky files to prove it.
  - `lessons.py`: loads and checks `lessons.json`; gives each lesson its check, test files and a version (changing one lesson re-grades only that lesson).
  - `roster.py`: every change to `participants.csv`: facilitator actions, undo, and applying graded results (results only go up).
  - `grade.py`: finds pull requests (GitHub, or an in-memory stand-in in tests) and decides what to grade.
  - `executor.py`: the only way participant code runs: a clean environment, timeouts, clean-up, and the CI sandbox user.
  - `checks.py`: the checks, built from the executor and a `RunningApp` (a jar or a container).
  - `leaderboard.py`: the single command line, the same commands the forms run.
- **Tests:** `python3 -m unittest discover grader/tests`. They run in CI on every change (*Test the grader*), including the workflow simulation in `grader/tests/simulate_workflows.py`, which runs every workflow's shell steps against a scratch repository. The check tests need a JDK and network access, and the container test needs Docker; each skips itself without them.
- **Security:** pull-request code runs only in the grading job, which has a read-only token. Within that job it runs as a separate `grader-sandbox` user that cannot write to the grader or its results, and everything it started is killed after each check. Saving results happens in a separate job. Run `leaderboard.py grade` locally only with `--no-run`, because without it the grader builds and runs code from the pull requests.
- **Walkthrough:** `walkthrough.py` serves this folder on 127.0.0.1 and opens `walkthrough/`, showing made-up example people (generated from `lessons.json`) unless run with `--real`. The words are in `walkthrough/steps.js`; it points at the leaderboard only through `data-tour="..."` attributes in `index.html`, and a test fails if one goes missing.
- **Preview locally:** run `python3 walkthrough.py` to see the page with made-up example people (or `--real` for the real scores); `python3 -m http.server 8000` (or `start.bat` on Windows) serves the plain page.
- **After merging changes to a check:** the next grading run re-grades every submission whose lesson's version changed (its check, the shared grader code, or its test files). The first run after this branch merges re-grades everything once, since older results have no per-lesson version.
