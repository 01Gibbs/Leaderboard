# Adding a lesson to the leaderboard with little effort

*Research note, 12 November 2026. Audience: project lead and facilitators.*

**Short answer:** Keep central grading, and make most new lessons need **no new Python**. To do that:

1. Read a lesson's tests from its own repository, pinned to a commit. Today they are copied into `grader/fixtures/`.
2. Describe the remaining checks in a short **acceptance spec**: HTTP calls, file rules, dependency versions and Dockerfile rules. Claude drafts the spec from `PROBLEM_STATEMENT.md`, and a facilitator reviews it.

With both in place, a Spring/Gradle/Docker lesson takes about **30 to 45 minutes** to add. Today a custom check takes half a day. GitHub Classroom is no longer an option because it was retired in August 2026.

---

## 1. What adding a lesson costs today

Every lesson is one entry in `lessons.json`, and its `check` field sets how much is automated (`README.md`, "Lessons"; `grader/checks.py:504`). The minutes below are my estimates, not measurements. No submission has been graded for real yet: every entry in `grader/results.json` has `passed: null`.

| Level | What someone has to do | Estimate |
|---|---|---|
| `none` | Add the entry and commit. A facilitator then marks each correct submission by hand (`FACILITATOR.md`). | 5 min to add, plus about 1 min per participant per workshop. The existing lessons have 3 to 10 PRs each (`gh pr list`). |
| `build` | Add the entry. This only proves the code compiles (`checks.py:291`). | 5 min |
| `tests` | Copy the test files into `grader/fixtures/<key>/` at the same paths (`checks.py:162,296`). Add a good and a bad case to `grader/tests/test_checks.py` (skill step 5, `.claude/skills/add-lesson/SKILL.md`). | 30 to 60 min |
| custom | Write a Python function (`checks.py:325-501`, 10 to 85 lines each), write reference submissions and tests, and run them with a JDK, plus Docker for container lessons. | 2 to 4 h, with Claude doing most of the typing |

All four current lessons needed custom checks. The `add-lesson` skill helps, but someone still has to write and review Python for every lesson.

## 2. Should the grader import tests from the lesson repository?

**Yes, pinned to a commit.** The evidence:

- **The copy is identical to the original.** `grader/fixtures/framework_upgrade/.../EmployeeApiTests.java` is byte-for-byte the same as the file on `AtulKumarSharma79/Frameworkupgrade`'s `main` branch (checked with `diff`). The copy adds no value, and it goes stale as soon as the instructor fixes a test.
- **Participants do edit tests.** PRs #1 and #3 on Frameworkupgrade changed `EmployeeApiTests.java`, replacing `admin123` with `{noop}admin123` (`gh api .../pulls/1/files`). The overlay already defeats this (`checks.py:162`). An import would keep that by overwriting the submission's test files with the upstream files.
- **Pin to a commit; do not read the moving default branch.** `grader_version()` hashes only `checks.py` and the fixtures (`grade.py:82`). If tests were read live from `main`, a test change would not trigger re-grading, and two participants could be graded against different tests. Putting the pinned commit in `lessons.json` makes a test change visible and re-grades everyone.
- **Tests can live in another repository.** For the REST API lesson, the PR repository holds only a README. The real tests and problem statement are in `AtulKumarSharma79/onboarding-tracker` (repository tree). The import therefore needs its own `repo` setting.
- **Package-bound tests do not fit from-scratch lessons.** Those tests are in `com.example.onboarding`, but the REST API lesson says "any base package you like" (`onboarding-tracker/PROBLEM_STATEMENT.md` §1). Lessons built from scratch need black-box HTTP checks instead, which is what the custom check does today (`checks.py:260`).

**Hidden tests.** The usual pattern keeps tests in a private repository that the grade job fetches with a read-only token stored as a secret. This does not suit our setup:

- The Leaderboard repository is public (`gh repo view`), so `grader/fixtures/` can already be read by anyone. The overlay stops participants *editing* tests, not *seeing* them.
- The job's built-in `GITHUB_TOKEN` cannot read another private repository, so we would need an extra secret in the same job that runs participant code (`.github/workflows/grade.yml`). That risk is reduced, not removed, by the sandbox user and `clean_env()` (`checks.py:60`).
- Failure reasons are published in `results.json` and would leak hidden test details anyway.

For 2-day internal workshops, visible but non-editable tests are enough. Whether workflow artifacts in a public repository can be downloaded by anyone is **unverified**, so do not pass hidden tests between jobs as artifacts.

## 3. Can grading come from `PROBLEM_STATEMENT.md`?

The problem statements already state "done" in checkable terms. The table below rates each requirement.

| Lesson | Machine-checkable | Human-judged |
|---|---|---|
| FizzBuzz (`excersize-1/README.md`) | Tests must kill planted bugs (custom mutation check, `checks.py:306`). | Coverage screenshot. |
| REST API (§5, §7) | Exact paths, the 201/200/400 cases and the date format. These carry 70% of the marks. Data surviving a restart could be checked by restarting. | H2 console visible, code structure (30% between them). Bruno screenshot. |
| Framework upgrade (§5.2, A.9) | Boot 3.5.x, no `javax.persistence`/`javax.validation`, removed properties gone, `commons-text` ≥ 1.10, starter tests pass, API unchanged, 401. C2 to C7 are all checkable. | The notes listing removed properties. Stretch S1 to S4. |
| Container image (§5.1, §8, `PLATFORM_STANDARDS.md`) | Approved pinned temurin base, JRE runtime, multi-stage, `.dockerignore`, non-root, app works in the container (70%). | Scan before/after table and gate (20%; findings change daily, per A.6). Write-up (10%). Screenshots. |

**A declarative spec is realistic for the three Spring lessons.** Their custom checks use only five kinds of rule:

- build the project and run tests;
- start the jar or image and send HTTP requests, comparing status and JSON fields;
- check that files must, or must not, match a pattern;
- check library versions inside the built jar;
- apply Dockerfile rules.

Dockerfile rules such as "the final stage uses a JRE" depend on the build stages, so they work better as named built-in rules (`multi_stage`, `non_root`, `base_image: <regex>`) than as free-form patterns. FizzBuzz's mutation testing should stay custom Python.

**Where the spec lives:** in this repository (`lessons/<key>.yml`), not inside `PROBLEM_STATEMENT.md`. There are three reasons:

- Facilitators do not own the lesson repositories; they belong to two personal accounts.
- A PR can edit the problem statement.
- Facilitators can then change grading without asking the lesson author.

The problem statement is still the source: Claude drafts the spec from its "What done looks like" column and lists every human-judged item for facilitators. A fenced block inside the statement could come later, if lesson authors want it.

## 4. GitHub features that could help

- **GitHub Classroom and its autograding.** Autograding ran as Actions workflows on each push to a Classroom-created repository. It offered I/O, pytest and run-command tests, and reported points in the Classroom dashboard ([docs](https://docs.github.com/en/education/manage-coursework-with-github-classroom/teach-with-github-classroom/use-autograding)). The docs do not mention PRs from forks. More importantly, **Classroom was retired on 28 August 2026**: "the GitHub Classroom website, APIs, and related services have now been decommissioned", and new sign-ups ended on 26 May 2026 ([changelog](https://github.blog/changelog/2026-08-27-github-classroom-deprecated), [sign-ups](https://github.blog/changelog/2026-05-26-github-classroom-sign-ups-are-no-longer-available)). **Not an option.**
- **Template repositories** create a repository with the same files, but "branches created from a template have unrelated histories", so you cannot open PRs between them ([docs](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository)). That makes them useless for submissions, but **useful for authors**: a lesson template with a `PROBLEM_STATEMENT.md` skeleton, the Gradle wrapper and a `.gitignore`. That would also prevent problems like the committed `.gradle/` folders in `excersize-1` (repository tree).
- **A workflow in each lesson repository that runs on `pull_request`.** For forks, "the `GITHUB_TOKEN` has read-only permissions" and "secrets are not passed to the runner". The workflow runs on the PR's merge commit ([docs](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows)). It has three problems:
  1. A participant can change the workflow in their own PR. GitHub's approval guidance tells maintainers to check "any edits to workflow files" ([docs](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/approving-workflow-runs-from-public-forks)). My inference is that a pass reported by this workflow cannot be trusted for scoring.
  2. "By default, all first-time contributors require approval to run workflows" ([settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)). Workshop PRs are never merged, so every participant counts as a first-time contributor. A facilitator would have to approve each PR unless the setting is relaxed to "new to GitHub" only.
  3. `pull_request_target` runs with base-repository rights; the docs warn that "running untrusted code on the `pull_request_target` trigger may lead to security vulnerabilities". **Do not use it to build PR code.**

  A **reusable workflow** (`uses: owner/Leaderboard/.github/workflows/x.yml@<sha>`, [docs](https://docs.github.com/en/actions/sharing-automations/reusing-workflows)) would keep each lesson's file to a few lines. Its value is **fast feedback inside the PR**, not trusted scores.
- **CODEOWNERS, rulesets and protected paths.** CODEOWNERS only requests reviews. It blocks a merge only with "Require review from Code Owners" ([docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)). Push rulesets with "Restrict file paths" apply to "a private or internal repository and that repository's entire fork network" ([docs](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)). Our lesson repositories are public, and we never merge PRs, so **neither stops a PR from editing tests**. The grader's overwrite is the right defence.
- **Check runs and commit statuses.** Only GitHub Apps can create check runs; other users can only read them ([docs](https://docs.github.com/en/rest/checks/runs)). Creating a commit status needs push access ([docs](https://docs.github.com/en/rest/commits/statuses)). The leaderboard *could* read the check run that a lesson-repository workflow produces, but problem 1 above makes that result untrustworthy.

## 5. Options compared

| Option | Setup once | Per new lesson | Per workshop | Resists cheating | Participant feedback | Security | Fit with the current leaderboard |
|---|---|---|---|---|---|---|---|
| **A. Today:** custom Python per lesson | done | 2–4 h | ~0 | High: our tests overwrite theirs, black-box HTTP | Up to 30 min later, in `results.json` (public) | Good: read-only grade job, sandbox user | Native |
| **B. Upstream tests (pinned) + acceptance spec** | 1–2 days: spec engine; port 3 lessons as proof | 30–45 min to draft, review and run against starter and reference | ~0 | High (same mechanism as A) | Same as A | Same as A. No new secrets | Native: a new generic `check` |
| **C. Upstream tests only;** everything else by hand (`none`/`tests`) | ~½ day | 10–15 min | 1 min × participants × human-judged lessons | Medium | Same as A for tested lessons | Same as A | Native |
| **D. Lesson-repository PR workflow** (reusable), leaderboard reads checks | 1–2 days, plus every lesson owner adds a file | 15 min, plus the owner's cooperation | Approve each first-time PR's workflow run | **Low**: PR can edit the workflow | Minutes, inside the PR | Fork token read-only. Risky if anyone switches to `pull_request_target` | Poor: needs a GitHub App or trust in unverified results |
| **E. GitHub Classroom** | — | — | — | — | — | — | **Retired 28 Aug 2026** |
| **F. Private hidden-tests repository** | ½ day | as B/C | ~0 | Highest in theory, but reasons leak | Same as A | Adds a secret in the job that runs PR code | Possible, but poor value here |

## 6. Recommendation

**Recommended: Option B, upstream tests plus an acceptance spec.**

What we would build:

1. **`tests_from` in `lessons.json`:**

   ```json
   "tests_from": {"repo": "AtulKumarSharma79/Frameworkupgrade", "ref": "<commit sha>", "paths": ["src/test/**"]}
   ```

   The grade job fetches these files read-only and overlays them as it does today. Include the ref in `grader_version()`, then delete `grader/fixtures/framework_upgrade/`.
2. **A generic `spec` check** that reads `lessons/<key>.yml`. It supports `build`, `run_tests`, `http` (start the bootJar or the Docker image, then a list of request, status and JSON-field expectations), `files_must_match` / `files_must_not_match`, `jar_dependency` minimum versions and the named Dockerfile rules. Most of the code already exists in `checks.py` as helpers (`RunningJar`, `http`, `dockerfile_problems`). The spec also has a `manual:` list of human-judged items, so facilitators know what to mark or award.
3. **Port** `rest_api`, `framework_upgrade` and `container_image` to specs. Their existing tests in `grader/tests/test_checks.py` must still pass. FizzBuzz stays custom.
4. **Update the `add-lesson` skill** so Claude reads `PROBLEM_STATEMENT.md` and drafts the spec. A facilitator approves it. Claude then proves the spec fails on the starter and passes on a reference solution.

What a facilitator does per new lesson (about 30 to 45 minutes):

1. Ask Claude Code to "add the lesson in owner/repo" (2 min).
2. Read the drafted spec and its "not checked automatically" list against the problem statement, and correct any thresholds (10 to 15 min).
3. Point Claude at a reference solution (a branch or repository from the lesson author). Without one, use `check: none` until one exists (5 min).
4. Wait for the starter and reference runs (10 to 20 min, mostly machine time), then merge.

**One condition:** each lesson author must provide a reference solution and keep the "What done looks like" column specific. Today Frameworkupgrade's C2, C6 and C7 rows are blank (§5.2), so their checks come from the appendix.

**Runner-up: Option C.** Import upstream tests and use `none` for everything else. It takes about half a day to build and 10 to 15 minutes per lesson. The cost moves to workshop days, when facilitators mark each person by hand.

**Later, optional:** add Option D's reusable PR workflow **only for feedback** (a comment or check in the participant's PR), while the central grader stays the only source of scores.
