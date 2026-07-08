# Logbook — notes for Claude Code

Logbook is a minimal, GitHub-native research notebook + task board for a
4–5 person research team. It replaces Notion-style tools with four concepts:

- **Pages** — markdown files in the team's private repo (math via KaTeX,
  code highlighting, tables, checkboxes, images, `[[wiki-links]]`)
- **Tasks** — GitHub Issues, rendered as a kanban board or list
  (`todo` = open, `doing` = open + `doing` label, `done` = closed;
  due dates are a `due: YYYY-MM-DD` line in the issue body)
- **Workspaces** — one folder per team member, plus shared `project/`
- **Dashboard** — computed from commits + issues; pinned page is
  `project/dashboard.md`

## Architecture — read before changing anything

- **Static SPA, zero dependencies, zero build step.** Plain ES modules
  served directly by GitHub Pages. There is deliberately no framework, no
  bundler, no npm. Do not introduce dependencies or a build step; that is
  the core design constraint, not an accident.
- All data lives in a GitHub repo, accessed client-side via the REST API
  with each user's fine-grained PAT (stored in localStorage under
  `logbook.config`). Every page save is a commit (contents API with sha
  for conflict detection → 409 handled in the editor).
- Optional `root` config scopes everything to a subfolder (e.g. `notes/`)
  so notes can live inside a larger project repo. `js/github.js` applies
  the prefix (`withRoot`/`stripRoot`); routes and views never see it.
- KaTeX + highlight.js are progressive enhancements from cdnjs; the app
  must keep working when they fail to load (see `js/markdown.js` fallbacks).
- Theme follows `prefers-color-scheme`; all colors are CSS variables in
  `css/app.css` (`:root` light, media-query override dark). No hardcoded
  colors outside the variable blocks.

## Layout

| Path | Purpose |
|---|---|
| `index.html` | shell + CDN enhancement tags |
| `js/app.js` | hash router, layout, sidebar |
| `js/config.js` | localStorage config (token, repo, root, apiBase override) |
| `js/github.js` | entire GitHub API surface used |
| `js/markdown.js` | built-in renderer; front matter (`status:`) parsing |
| `js/state.js` | session cache (workspace list, current user) |
| `js/views/*.js` | one file per screen (setup, home, workspace, page, tasks, find) |
| `css/app.css` | all styling, light+dark variables |
| `starter/` | initial structure for the team's data repo (not served) |
| `test/mock-github.mjs` | in-memory mock of the API slice (arg2: port, arg3: root prefix) |
| `test/e2e.mjs`, `test/e2e-extras.mjs` | Playwright smoke tests + screenshots |

## Testing

```
node test/mock-github.mjs 8788 &          # mock API (in-memory, reset each run)
node test/e2e.mjs                         # main pass (light, no root)
node test/e2e-extras.mjs                  # dark mode + root-folder pass
```

Tests print `FAIL: ...` lines and exit non-zero on failure; screenshots land
in `test/shot-*.png`. Always restart the mock between runs (state persists).
The e2e harness points the app at the mock via the `apiBase` key in
`logbook.config`.

## Deployment model

GitHub Pages, "deploy from branch" on `main` — merged = deployed, no CI.
`main` should be protected (PR + 1 review). The data repo is separate and
private; this app repo contains no research content.

## Roadmap (phase 2/3, only when the team feels the pain)

Image paste-to-upload (commit to `assets/`, insert link) · drag-and-drop on
the board · content search · in-app page history (list commits for a file) ·
"someone is editing" hint (recent-commit check on editor open).
