# Logbook — notes for Claude Code

Logbook is the team's research notebook + task board: a zero-dependency
static SPA that reads/writes markdown in this repo's `notes/` folder and
uses this repo's Issues as tasks, via each user's fine-grained PAT.

- **No dependencies, no build step, no framework.** Core design constraint,
  not an accident. Plain ES modules only.
- Deployed at https://uchicago-xlab.github.io/tcw-logbook/ from the public
  mirror repo `uchicago-xlab/tcw-logbook` (app code only — this private repo
  can't use Pages on the org's free plan). **Never edit the mirror.** After
  changing app code here: copy `index.html js/ css/` into a clone of the
  mirror and push as one snapshot commit. Don't use `git subtree` — it would
  publish this repo's commit messages.
- Layout: `js/app.js` hash router · `js/github.js` API layer (applies the
  `root` = `notes` prefix; views never see it) · `js/cache.js` session
  stale-while-revalidate cache (sidebar, tasks, viewed pages — never the
  editor, whose sha drives conflict detection) · `js/markdown.js` renderer ·
  `js/views/*.js` one per screen · `css/app.css` all styling (light/dark via
  CSS variables only).
- KaTeX + highlight.js load from cdnjs as optional enhancements; the app
  must keep working when they fail.
