// The walkthrough engine: shows one step at a time. A step either highlights a [data-tour] element on the live
// leaderboard (loaded in the iframe) or shows its own stage, with its text in the side panel.
// Content lives in steps.js; this file only displays it.

const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The area an element covers. An element with `display: contents` (the leaderboard's cell groups on wide
// screens) has no box of its own, so it covers the area of its children.
function areaOf(el) {
  if (el.getClientRects().length) return el.getBoundingClientRect();
  const boxes = [...el.children].map(areaOf).filter(Boolean);
  if (!boxes.length) return null;
  const top = Math.min(...boxes.map((b) => b.top)), left = Math.min(...boxes.map((b) => b.left));
  const bottom = Math.max(...boxes.map((b) => b.bottom)), right = Math.max(...boxes.map((b) => b.right));
  return { top, left, width: right - left, height: bottom - top, bottom, right };
}

export function startTour(steps, ui) {
  const { frame, stage, spot, chapterNav, chapter, title, text, note, counter, back, next } = ui;
  const frameLoaded = new Promise((resolve) => {
    if (frame.contentDocument?.readyState === 'complete' && frame.contentDocument.URL !== 'about:blank') resolve();
    else frame.addEventListener('load', resolve, { once: true });
  });
  let current = -1;
  let target = null;
  let generation = 0; // which show() call is current, so a slow step cannot finish after the reader has moved on

  const chapters = [...new Set(steps.map((s) => s.chapter))];
  chapterNav.replaceChildren(...chapters.map((name) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = name;
    b.addEventListener('click', () => show(steps.findIndex((s) => s.chapter === name)));
    return b;
  }));

  function place() {
    const r = target && target.isConnected ? areaOf(target) : null;
    if (!r || !r.width) {
      spot.hidden = true;
      return;
    }
    const pad = 6;
    Object.assign(spot.style, { top: `${r.top - pad}px`, left: `${r.left - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
    spot.hidden = false;
  }

  // The first of the step's targets that is visible. The board fills in after it has loaded the scores, so
  // wait for that; once it has, a target that is still not visible is hidden at this width (the header row is
  // on narrow screens), so move on quickly.
  async function findTarget(names, token) {
    await frameLoaded;
    const doc = frame.contentDocument;
    for (let i = 0, settled = 0; i < 30 && token === generation && settled < 5; i++) {
      for (const name of names) {
        const el = doc.querySelector(`[data-tour="${name}"]`);
        if (el && areaOf(el)?.width) return el;
      }
      if (doc.querySelector('[data-tour="first-row"]')) settled++;
      await sleep(100);
    }
    return null;
  }

  async function show(i) {
    i = Math.max(0, Math.min(steps.length - 1, i));
    if (i === current) return;
    const token = ++generation;
    current = i;
    const step = steps[i];
    history.replaceState(null, '', `#${i + 1}`);

    chapter.textContent = step.chapter;
    title.textContent = step.title;
    text.innerHTML = step.text || '';
    note.hidden = true;
    counter.textContent = `${i + 1} of ${steps.length}`;
    back.disabled = i === 0;
    next.textContent = i === steps.length - 1 ? 'Start again' : 'Next';
    [...chapterNav.children].forEach((b) => b.setAttribute('aria-current', String(b.textContent === step.chapter)));

    target = null;
    spot.hidden = true;
    if (step.stage) {
      stage.innerHTML = step.stage;
      stage.hidden = false;
      stage.scrollTop = 0;
      return;
    }
    stage.hidden = true;
    const el = await findTarget([].concat(step.target), token);
    if (token !== generation) return;
    if (!el) {
      note.textContent = 'This part of the board is hidden at this window size, or has nothing to show yet. Try a wider window.';
      note.hidden = false;
      return;
    }
    target = el;
    (el.getClientRects().length ? el : el.firstElementChild).scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' });
    place();
  }

  // Keep the highlight on its element while the board scrolls, resizes or re-renders.
  frameLoaded.then(() => {
    frame.contentWindow.addEventListener('scroll', place, { passive: true });
    frame.contentWindow.addEventListener('resize', place);
    new MutationObserver(() => {
      if (target && !target.isConnected && current >= 0 && steps[current].target) {
        target = frame.contentDocument.querySelector(`[data-tour="${steps[current].target}"]`);
      }
      place();
    }).observe(frame.contentDocument.body, { childList: true, subtree: true, attributes: true });
  });
  addEventListener('resize', place);

  back.addEventListener('click', () => show(current - 1));
  next.addEventListener('click', () => show(current === steps.length - 1 ? 0 : current + 1));
  addEventListener('keydown', (e) => {
    if (e.target.closest?.('input, textarea, select') || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); next.click(); }
    if (e.key === 'ArrowLeft' && !back.disabled) { e.preventDefault(); back.click(); }
  });
  addEventListener('hashchange', () => show(parseInt(location.hash.slice(1), 10) - 1 || 0));

  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
}
