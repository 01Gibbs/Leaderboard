# Facilitator guide

Everything is done from the repository on GitHub. You don't need to install anything.

For a guided tour first, run `python3 walkthrough.py` (Windows: `py walkthrough.py`) in a copy of this repository. It opens in your browser.

**To make a change:** open the repository → **Actions** tab → pick a *Facilitator:* action on the left → **Run workflow** (top right) → fill in the form → **Run workflow**.

After about 30 seconds, the run shows a ✅ or ❌ with a one-line summary of what changed. Click the run to see it. The public page updates a minute or two later.

When a form asks for a **person**, use either their name as it appears on the leaderboard or their GitHub username. Upper or lower case doesn't matter. If nobody matches, nothing changes and the run suggests close matches.

## I want to…

| …do this | Use | Fill in |
|---|---|---|
| Give points for helping a colleague | **Facilitator: Award points** | person, *helped*, how many times |
| Give points for a stretch task | **Facilitator: Award points** | person, *stretch*, how many tasks |
| Give any other points | **Facilitator: Award points** | person, *bonus*, how many points |
| Take points away | **Facilitator: Award points** | the same, with a minus sign, e.g. `-1` |
| Show someone's real name instead of their GitHub username | **Facilitator: Rename a person** | GitHub username, real name |
| Fix someone who appears twice | **Facilitator: Merge duplicate people** | the row to keep, the duplicate |
| Mark an exercise correct that you checked by hand | **Facilitator: Mark an exercise** | person, exercise key (see below), *correct* |
| Add someone who hasn't opened a pull request yet | **Facilitator: Add a person** | name, GitHub username if known |
| Reverse a mistake | **Facilitator: Undo last change** | nothing |
| Grade new pull requests right now | **Grade submissions** | nothing (it also runs every 30 minutes) |

## Points
Submitted **10**, correct **30**, each stretch task **+5**, each help **+5**, and bonus points count one for one. The first 3 pull requests on each exercise earn their authors a stretch credit automatically. Equal points are ranked by number of correct exercises.

## Good to know
- **New participants appear by themselves** when they open a pull request on an exercise repository. They show under their GitHub profile name or username until you rename them.
- **Merging** keeps the higher value of every column. That means the best result for each exercise and the larger stretch, helped and bonus numbers, so nobody loses points. The kept row remembers both GitHub accounts, so the duplicate doesn't come back.
- **Undo** reverses the latest facilitator change, and only the cells that change touched. Run it again to go back one more. Anything changed since, by the grader or by anyone else, is kept; if a cell was changed again since, undo leaves it alone and says so. Each run lists the five most recent changes and who made them.
- **Two facilitators at once is fine.** If two changes are saved at the same moment, both land.
- **Results only go up.** The automatic grader never lowers a result, so it never overwrites your changes. If you mark an exercise lower than a pull request earned, the next grading run raises it again.
- **Exercise keys** for *Mark an exercise* are in [`lessons.json`](lessons.json): `fizzbuzz`, `rest_api`, `framework_upgrade`, `container_image`.
- **Why a submission isn't *Correct* yet:** open `grader/results.json` and search for the person's GitHub username. Each pull request lists the reasons it passed or failed.
- **A run with ❌** didn't change anything. Click it to read the reason, fix the form and run it again.
