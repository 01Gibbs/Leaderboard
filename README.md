# Java Exercise Leaderboard

A static page that ranks participants across the REST API, framework upgrade and container image exercises. It has no server and no build step. The scores live in `participants.csv`.

## Updating scores
Edit `participants.csv` (in Excel, a text editor, or GitHub's web editor) and commit. The page picks up the new file after GitHub Pages redeploys, usually within a minute or two.

| Column | Values |
|---|---|
| `name` | The participant's name. Rows with no name are skipped. |
| `rest_api` | `correct`, `submitted` or `none` |
| `framework_upgrade` | `correct`, `submitted` or `none` |
| `container_image` | `correct`, `submitted` or `none` |
| `stretch` | Number of stretch tasks completed |
| `helped` | Number of times the person helped a colleague |

Names containing a comma must be wrapped in double quotes, for example `"Rao, Asha"`.

## Points
Submitted 10, correct solution 30, each stretch task +5, each time helping a colleague +5. To change the weights or the exercise names, edit the `PTS` and `TRACKS` constants near the bottom of `index.html`.

## Trying it locally
Browsers block loading the CSV when `index.html` is opened straight from disk (double-clicked). Either:
- run `start.bat` (Windows, needs Python), which serves the folder and opens http://localhost:8000/index.html, or
- open `index.html` directly and use the **Choose participants.csv** button that appears.

To serve it by hand: `python -m http.server 8000`. To preview with made-up data, copy `participants.sample.csv` over `participants.csv` locally, and do not commit that copy.

## Publishing on GitHub Pages
1. Push this folder to a public repository.
2. In the repository, open **Settings**, then **Pages**.
3. Under **Build and deployment**, choose **Deploy from a branch**, pick the `main` branch and the `/ (root)` folder, and save.
4. The site appears at `https://<your-username>.github.io/<repository-name>/`.

The page and `participants.csv` are public, so anyone with the link can see every name and score.
