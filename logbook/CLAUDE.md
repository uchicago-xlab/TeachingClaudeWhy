# Logbook — notes for Claude Code

Logbook is the team's research notebook + task board: a zero-dependency
static SPA that reads/writes markdown in this repo's `notes/` folder via each
user's fine-grained PAT.

- The landing screen is **the board** (`js/views/todo.js`), backed entirely by
  the single file `notes/Project/Todo.md`: each `## Name` heading is a column
  and each `- [ ]` line an item. It does not use GitHub Issues — that was the
  old Tasks screen, removed 2026-09-08 along with the computed Dashboard,
  because nobody had opened an issue since week 1. Keep the file plain: the
  board's whole point is that it stays a readable checklist on GitHub and in
  the page editor. Every edit is a read-modify-write that locates the item by
  its **text**, never a line number, which is what lets two people edit at
  once; anything that isn't a task line is preserved untouched.

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
  stale-while-revalidate cache (sidebar, viewed pages — never the editor or
  the board, whose shas drive conflict detection) · `js/markdown.js` renderer ·
  `js/views/*.js` one per screen · `css/app.css` all styling (light/dark via
  CSS variables only).
- KaTeX + highlight.js load from cdnjs as optional enhancements; the app
  must keep working when they fail.
