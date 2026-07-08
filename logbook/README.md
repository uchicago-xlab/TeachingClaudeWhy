# Logbook

A minimal, GitHub-native research notebook + task board for a small team.
Notion-ish, minus the overhead: **four concepts** — pages, tasks, workspaces,
and one shared dashboard.

- **Pages** are markdown files in a private GitHub repo (with math, code, tables, images)
- **Tasks** are GitHub Issues, shown as a list or kanban board
- **Workspaces** are folders — one per team member, plus a shared `project/` space
- **Dashboard** is computed from commits + issues; nobody maintains it

No server, no database, no build step, no dependencies to install.
Every save is a git commit, so version history is free and the data outlives
the tool: if Logbook vanished tomorrow, your notes are still plain markdown.
The UI follows your system's light/dark theme automatically.

---

## Setup (once, ~15 minutes for the whole team)

### 1. Decide where notes live, and create the app repo

**Option A — dedicated data repo.** Create a **private** repo, e.g.
`research-notes`. Copy the contents of [`starter/`](starter/) into it, and add
a folder per team member (the folder name shows up as their workspace).

**Option B — notes inside your existing project repo.** If the team already
has one repo for the whole project (code, analysis, paper), put notes in a
subfolder instead: create `notes/` in that repo, copy `starter/`'s contents
into `notes/`, and add per-member folders inside it. During app setup, enter
`notes` in the "Notes folder" field — workspaces, pages, and the activity
feed then all stay inside that folder, and tasks use the repo's normal
Issues. (Bonus: the dashboard's activity feed shows only note edits, not
code commits.)

Either way, everyone needs **Write** access to that repo
(Settings → Collaborators).

**The app repo** is separate either way: create e.g. `logbook`, push these
files to `main`. It contains no research content — only the app's code — so
it can safely be public. (A private app repo works too if your GitHub plan
supports Pages on private repos, e.g. Pro/Team/education accounts.)

### 2. Turn on GitHub Pages for the app repo

Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, folder `/ (root)`.

A minute later the app is live at `https://<owner>.github.io/logbook/`.

### 3. Protect `main` so app changes get reviewed

Settings → Branches → Add branch ruleset for `main`:
- ✅ Require a pull request before merging (1 approval)

Now anyone on the team can improve the app via PR, and nothing goes live
until it's reviewed and merged — merged *is* deployed.

### 4. Each team member: token setup (~2 minutes)

Open the app URL. It walks you through it, but for reference:

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate new token
2. Name it `logbook`, set expiration as you like (you can renew any time)
3. **Repository access**: *Only select repositories* → choose the data repo
4. **Permissions** → Repository permissions:
   - **Contents: Read and write**
   - **Issues: Read and write**
5. Generate, copy, paste into Logbook's setup screen along with the data
   repo's `owner/name` (and the notes subfolder, if you chose Option B).

The token is stored in your browser's localStorage only and is sent
exclusively to `api.github.com`. Don't paste it anywhere else.

---

## Using it

- **Pages**: markdown with `$inline$` and `$$block$$` math (KaTeX), fenced
  code blocks with syntax highlighting, tables, task-list checkboxes, images,
  and `[[wiki-links]]` to other pages. `⌘S` / `Ctrl-S` saves — each save is a
  commit, so the page's full history is in git.
- **Page status**: each page has a status chip (`active` / `paused` / `done`)
  stored as front matter. Pages marked `active` surface on the dashboard —
  that's how the team sees "what's moving" without anyone writing status reports.
- **Tasks**: create from the Tasks screen; they're real GitHub Issues, so
  they also work from GitHub's web UI, mobile app, and notifications.
  `todo` = open issue, `doing` = open + `doing` label, `done` = closed.
  Optional due date is a `due: YYYY-MM-DD` line in the issue body.
- **Dashboard**: pinned `project/dashboard.md`, recent commits across all
  workspaces, open-task count, and everyone's active pages.
- **Conflicts**: if two people edit the same page at once (rare on an async
  team), the second save is rejected rather than silently overwriting —
  you'll get a warning and can reconcile.

## Changing the app itself

The app is ~1,000 lines of dependency-free JS in `js/` — no framework, no
build step. Edit, open a PR, merge: the change is live. Math and code
highlighting come from KaTeX/highlight.js on cdnjs and degrade gracefully
if the CDN is unreachable.

| File | What it does |
|---|---|
| `js/app.js` | hash router + layout + sidebar |
| `js/github.js` | the slice of the GitHub API we use |
| `js/markdown.js` | built-in markdown renderer (math/code/tables/wiki-links) |
| `js/views/*.js` | one file per screen |
| `css/app.css` | all styling |

## Roadmap (add only when the pain is real)

Phase 2: image paste-to-upload · full board drag-and-drop · content search.
Phase 3: in-app page history · "someone is editing" hint · keyboard palette.
