/**
 * Make the embedded web example (`iframe.cs-demo`) part of the page rather than a box in it.
 *
 * - Height: the frame grows and shrinks with the example's content, so the page scrolls and the
 *   frame never does.
 * - Theme: the docs' theme toggle (Furo's `data-theme` on the body: auto, light or dark) drives
 *   the example's (`data-theme` on its root, unset to follow the system), and the example's own
 *   toggle is removed so there is one switch on the page.
 *
 * Both need the frame's document, which is reachable because the example is served from the same
 * origin. Where it is not (a page opened from disk), the frame keeps its CSS height and its own
 * toggle, and still works.
 */

const FRAMES = document.querySelectorAll('iframe.cs-demo');

/** Furo's theme, as the example's: "light", "dark", or undefined to follow the system. */
const exampleTheme = () => {
  const theme = document.body.dataset.theme;
  return theme === 'light' || theme === 'dark' ? theme : undefined;
};

const applyTheme = (doc) => {
  const theme = exampleTheme();
  if (theme === undefined) {
    delete doc.documentElement.dataset.theme;
  } else {
    doc.documentElement.dataset.theme = theme;
  }
};

/** Track the example's body: its height is its content's, whatever the frame's height is. */
const followHeight = (frame, doc) => {
  const fit = () => {
    frame.style.blockSize = `${Math.ceil(doc.body.getBoundingClientRect().height)}px`;
  };
  new ResizeObserver(fit).observe(doc.body);
  fit();
};

const embed = (frame) => {
  let doc;
  try {
    doc = frame.contentDocument;
  } catch {
    return;
  }
  if (!doc?.body) {
    return;
  }
  doc.querySelector('#theme')?.remove();
  applyTheme(doc);
  new MutationObserver(() => applyTheme(doc)).observe(document.body, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  followHeight(frame, doc);
};

for (const frame of FRAMES) {
  // A frame that finished loading before this module ran has already fired `load`.
  if (frame.contentDocument?.readyState === 'complete' && frame.contentDocument.body?.childElementCount) {
    embed(frame);
  }
  frame.addEventListener('load', () => embed(frame));
}
