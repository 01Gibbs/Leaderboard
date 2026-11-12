# A one-command guided walkthrough of the leaderboard

*Research note, 12 November 2026. Audience: project lead and maintainers.*

**Short answer:** Write a small vanilla spotlight + tooltip tour (about 150 lines). Serve it with `walkthrough.py`, which uses only the standard library: `ThreadingHTTPServer` bound to `127.0.0.1` on a free port, then `webbrowser.open`. The tour script is added to `index.html` only while it is being served this way, so the public page does not change. driver.js (MIT) is the fallback if the hand-written tour grows too big. Shepherd.js and intro.js need a paid licence for business use.

Versions, sizes and code facts marked *(inspected)* come from the npm tarballs I downloaded today. I measured sizes with `gzip -9` on the shipped files.

---

## 1. Tour libraries

| | driver.js | Shepherd.js | intro.js | Hand-written |
|---|---|---|---|---|
| Latest version | 1.12.1, 12 Nov 2026 [npm][d-npm] | 16.0.0, 11 Nov 2026 [npm][s-npm] | 8.6.0, 21 Sep 2026 [release][i-rel] | n/a |
| Licence | **MIT** [LICENSE][d-lic] | **AGPL-3.0 or commercial** ($50 / $300) [LICENSE][s-lic], [pricing][s-price] | **AGPL-3.0 or commercial** [license.md][i-lic] | ours |
| Size, min+gz (JS + CSS) | 14.2 KB + 1.9 KB *(inspected)* | 10.8 KB + 1.0 KB (theme +1.3 KB) *(inspected)* | 20.3 KB + 2.0 KB *(inspected)* | about 3 KB, estimated |
| Runtime dependencies | none [package.json][d-pkg] | none listed; Floating UI is bundled in *(inspected)* | none [package.json][i-pkg] | none |
| Vendor as one offline file | yes: `dist/driver.js.iife.js` + `driver.css` | yes: `dist/js/shepherd.mjs` has no imports, but it is ESM only, so it needs `<script type="module">` [docs][s-docs] | yes: `minified/intro.min.js` + `introjs.min.css` | yes |
| Elements inside a same-origin iframe | not documented [config][d-cfg]; tour code must run inside the page | not documented [docs][s-docs]; same | not documented [options][i-opt]; same | same |
| Arrow keys / Esc | yes, `allowKeyboardControl` [config][d-cfg] | yes, `keyboardNavigation`, `exitOnEsc` [docs][s-docs] | yes, `keyboardNavigation`, `exitOnEsc` [options][i-opt] | must be written |
| Focus and screen readers | `role="dialog"`, `aria-labelledby`, Tab handling, an `aria-live` announcement *(inspected)*. No `aria-modal`. | native `<dialog>`, `aria-labelledby`/`aria-label` [docs][s-docs]; Tab focus trap *(inspected)* | `role="dialog"`, `aria-label`. No focus trap or focus return found *(inspected)*. | must be written |
| `prefers-reduced-motion` | yes, in CSS *(inspected)* | yes, overlay transitions run only under `no-preference` *(inspected)* | no; the only media query is colour scheme *(inspected)* | must be written |
| Maintenance | active: 1 open issue, 0 open PRs, 27k stars [repo][d-gh] | active: 9 issues, 5 PRs [repo][s-gh] | active: 25 issues, 27 PRs [repo][i-gh] | ours |

Notes:

- **Licences.** We use this for business, so Shepherd.js or intro.js would need a paid licence. Shepherd's pricing page says a licence is needed for "a commercial app, website, or plugin" [pricing][s-price]. intro.js says the same in its licence file [license.md][i-lic], which links to `introjs.com/#commercial`. I did not verify intro.js prices: `introjs.com/pricing` returned 404.
- **Iframes.** All three accept a DOM element as the target [config][d-cfg], [docs][s-docs]. But they position the overlay with the host document's coordinates. A target inside an iframe therefore needs offset maths that none of them document. *Inference, not tested.* The tour code should run inside `index.html`. For the other places (Actions forms, `lessons.json`, results), use explanation steps that link to them; do not try to embed github.com, which refuses to load in frames.
- **Focus return when the tour closes.** driver.js tracks `document.activeElement` heavily *(inspected)*. I did not test whether it returns focus to the button that started the tour. *Unverified* for all three.

## 2. Serving with one command, standard library only

Outline of `walkthrough.py`:

```python
import http.server, json, subprocess, webbrowser, functools, pathlib
ROOT = pathlib.Path(__file__).resolve().parent

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/_walkthrough/context.json":
            body = json.dumps(context()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()   # "/" can be intercepted here to add the tour <script>

handler = functools.partial(Handler, directory=str(ROOT))
with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd:
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Walkthrough running at {url}  (press Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
```

Pitfalls:

- **Port already in use.** Bind to port `0` and the operating system picks a free port. Read the chosen port back from `server_address` [socketserver][py-ss], [socket][py-sock]. This avoids the `OSError` you get when port 8000 is taken.
- **Threads.** Use `ThreadingHTTPServer` rather than `HTTPServer`. Browsers pre-open sockets, "on which HTTPServer would wait indefinitely" [http.server][py-http].
- **`directory=`.** Pass it to `SimpleHTTPRequestHandler` (3.7+) so the script works from any working directory [http.server][py-http].
- **Bind to 127.0.0.1, not 0.0.0.0.** The `http.server` command line "binds itself to all interfaces" by default, and the docs warn it "is not recommended for production. It only implements basic security checks" [http.server][py-http]. Binding to loopback keeps the files off the office or café network.
- **Why not just open `index.html`?** The page loads data with `fetch()` (`index.html:359`, `:363`). The Fetch standard leaves `file:` URLs undefined ("left as an exercise for the reader") [Fetch][fetch-file], and browsers block them in practice [MDN][mdn-file]. Module scripts loaded from `file://` are blocked too. So the page has to be served over HTTP.
- **Windows commands.** With the Python install manager, `python`, `py` and `pymanager` should all work after install [Windows docs][py-win]. If `python` "opens the Store app", the troubleshooting table says to check that the install manager is installed and to look at "Manage app execution aliases" [Windows docs][py-win]. `python3` is not one of the documented commands on Windows [Windows docs][py-win]. Document it as: macOS/Linux `python3 walkthrough.py`; Windows `py walkthrough.py` (or `python walkthrough.py`).
- **Opening the browser.** `webbrowser.open()` uses the platform default browser. It returns `False` when it cannot open one, for example on a headless Linux machine [webbrowser][py-wb]. Always print the URL as well.
- **Ctrl+C.** `serve_forever()` polls for shutdown every `poll_interval` (0.5 s by default) [socketserver][py-ss]. Python turns SIGINT into `KeyboardInterrupt` [signal][py-sig]. Catch it so the user sees "Stopped." instead of a traceback. The `with` block closes the socket.
- **Dynamic JSON.** Override `do_GET` and use `send_response` / `send_header` / `end_headers` / `wfile`. Note that "end_headers() MUST BE called" [http.server][py-http]. Build the context from `subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True)` [subprocess][py-sp] and from `lessons.json`. Fall back gracefully when git is missing or the folder is not a repository. Turn the remote into the Actions URL (`https://github.com/<owner>/<repo>/actions`). Override `log_message` to keep the terminal quiet for a non-technical user [http.server][py-http].

## 3. Accessibility basics (WAI-ARIA dialog pattern)

The APG modal dialog pattern [APG][apg] says:

- The container has `role="dialog"`, plus `aria-labelledby` pointing at the visible step title (or `aria-label`). `aria-describedby` is optional, for simple text.
- Use `aria-modal="true"` only if the page behind really is inert and visually obscured. A spotlight tour usually leaves the highlighted element visible, so either make the rest inert or leave `aria-modal` off.
- When the dialog opens, focus moves into it. Tab and Shift+Tab wrap inside it. **Escape closes it.** When it closes, focus returns to the element that opened it (the "Start tour" button).
- Also from the APG keyboard guidance [APG keyboard][apg-kbd]: every control must be a real `<button>`, and the focus must be visible. Use arrow keys for Back and Next only while focus is inside the dialog, and never take over keys the page itself uses. Under `prefers-reduced-motion: reduce`, turn off spotlight transitions and smooth scrolling [MDN][mdn-rm].

## Recommendation

**Hand-written vanilla spotlight + tooltip, served by a standard-library `walkthrough.py`. Keep driver.js 1.12.1 (MIT, one IIFE file) as the vendored fallback.**

Why: a hand-written tour keeps the repo's rules intact. There are no dependencies and no build step, and nothing is fetched except Google Fonts. It also avoids the AGPL/commercial question that rules out Shepherd.js and intro.js for business use. About 150 lines covers what the APG dialog pattern requires, and we control focus return and reduced motion, which I could not verify in the libraries. The server adds the tour script only when serving it locally (`walkthrough.py` intercepts `/`), so the public GitHub Pages site stays exactly as it is.

[d-npm]: https://www.npmjs.com/package/driver.js
[d-lic]: https://github.com/nilbuild/driver.js/blob/master/license
[d-pkg]: https://github.com/nilbuild/driver.js/blob/master/packages/driver/package.json
[d-cfg]: https://driverjs.com/docs/configuration
[d-gh]: https://github.com/nilbuild/driver.js
[s-npm]: https://www.npmjs.com/package/shepherd.js
[s-lic]: https://github.com/shipshapecode/shepherd/blob/main/LICENSE.md
[s-price]: https://shepherdjs.dev/pricing
[s-docs]: https://docs.shepherdjs.dev/guides/usage/
[s-gh]: https://github.com/shipshapecode/shepherd
[i-rel]: https://github.com/usablica/intro.js/releases/tag/v8.6.0
[i-lic]: https://github.com/usablica/intro.js/blob/master/license.md
[i-pkg]: https://github.com/usablica/intro.js/blob/master/package.json
[i-opt]: https://introjs.com/docs/tour/options
[i-gh]: https://github.com/usablica/intro.js
[py-http]: https://docs.python.org/3/library/http.server.html
[py-ss]: https://docs.python.org/3/library/socketserver.html
[py-sock]: https://docs.python.org/3/library/socket.html#socket-families
[py-win]: https://docs.python.org/3/using/windows.html
[py-wb]: https://docs.python.org/3/library/webbrowser.html
[py-sig]: https://docs.python.org/3/library/signal.html#execution-of-python-signal-handlers
[py-sp]: https://docs.python.org/3/library/subprocess.html#subprocess.run
[fetch-file]: https://fetch.spec.whatwg.org/#scheme-fetch
[mdn-file]: https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS/Errors/CORSRequestNotHttp
[mdn-rm]: https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion
[apg]: https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/
[apg-kbd]: https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/
