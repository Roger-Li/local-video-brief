---
name: manual-check
description: Kill stale servers, launch fresh backend + frontend, then walk the user through a guided manual verification checklist for recent code changes. Use when the user wants to visually/manually test the app UI after making changes.
argument-hint: [--port 8010] [--frontend-port 5173] [--provider fallback|omlx]
---

# Guided Manual E2E Check

Kill stale processes, launch a fresh backend and frontend, then present a step-by-step checklist so the user can manually verify recent code changes in the browser.

## Arguments

- `$ARGUMENTS` contains optional flags:
  - `--port <N>` — backend port (default: 8010)
  - `--frontend-port <N>` — frontend dev server port (default: 5173)
  - `--provider <fallback|mlx|omlx>` — summarizer provider (default: from `.env` — do NOT override unless the user explicitly asks)
- Parse flags from `$ARGUMENTS`. Anything not recognised is ignored.

## Step 1 — Kill stale processes

```bash
# Kill any backend on the target port
lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
# Kill any frontend dev server on the target frontend port
lsof -ti :$FRONTEND_PORT | xargs kill -9 2>/dev/null || true
# Small grace period
sleep 1
```

Confirm both ports are free before proceeding.

## Step 2 — Detect environment

1. Python: check `OVS_TEST_PYTHON`, then `$HOME/ml-env/bin/python`, then `.venv/bin/python`.
2. Read `.env` to determine the configured provider. Do NOT override `OVS_SUMMARIZER_PROVIDER` unless `--provider` was explicitly passed. The `.env` is the source of truth.
3. If provider is `omlx`: read `OVS_OMLX_BASE_URL`, `OVS_OMLX_MODEL` from `.env`. Print effective config.
4. Print the resolved settings: provider, python path, ports.

## Step 3 — Launch backend

**IMPORTANT:** Long-running servers MUST be launched with `& disown` inside a **foreground** `Bash` call (do NOT use `run_in_background: true`). The `run_in_background` parameter creates a tracked task whose process group is killed when the task "completes." Use `& disown` to detach the server from the shell so it survives.

Launch and health-check in a single foreground Bash call:

```bash
# Only set OVS_SUMMARIZER_PROVIDER if --provider was explicitly passed.
# Otherwise let .env determine the provider (usually omlx).
OVS_ENABLE_STUDY_PACK=true \
OVS_ENABLE_MLX_ASR=true \
${PROVIDER:+OVS_SUMMARIZER_PROVIDER=$PROVIDER} \
$PYTHON -m uvicorn backend.app.main:app --host 127.0.0.1 --port $PORT \
  > artifacts/test-runs/backend-manual-${PORT}.log 2>&1 & disown
sleep 2
for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:$PORT/health >/dev/null 2>&1 && echo "Backend healthy" && break
  sleep 1
done
curl -fsS http://127.0.0.1:$PORT/health >/dev/null 2>&1 || \
  (echo "FAILED — log tail:" && tail -30 artifacts/test-runs/backend-manual-${PORT}.log)
```

If it doesn't start, show log tail and abort.

## Step 4 — Launch frontend

Same rule: `& disown` in a foreground Bash call, then verify in the same command.

```bash
cd frontend && VITE_API_BASE_URL=http://127.0.0.1:$PORT npx vite --port $FRONTEND_PORT > /dev/null 2>&1 & disown
sleep 3
curl -fsS -o /dev/null http://localhost:$FRONTEND_PORT && echo "Frontend running" || echo "Frontend not responding"
```

## Step 5 — Present the checklist

Print a clear, numbered checklist tailored to the **current worktree changes**. To build the checklist:

1. Run `git diff main --stat` in the worktree to see which files changed.
2. Map changed files to feature areas:
   - `study_pack.py` → section refinement checks
   - `StudyGuideView.tsx` → frontend study guide rendering checks
   - `summarizer.py` → summarization quality checks
   - `pipeline.py` → pipeline flow checks
   - `JobForm.tsx` → form/options UI checks
   - `styles.css` → visual styling checks
3. Always include baseline checks (submit job, tabs render, export works).
4. Add feature-specific checks based on the diff.

### Checklist format

```
## Manual Verification Checklist

Backend: http://127.0.0.1:$PORT
Frontend: http://localhost:$FRONTEND_PORT

### Baseline
1. [ ] Open http://localhost:$FRONTEND_PORT in browser
2. [ ] Paste a video URL and submit
3. [ ] Job progresses through stages (check progress indicator)
4. [ ] Job completes — three tabs appear: Summary | Study Guide | Transcript
5. [ ] Summary tab: chapter cards with bilingual summaries
6. [ ] Transcript tab: segment rows render

### Feature: <detected feature area>
N. [ ] <specific check for this feature>
...

### Cleanup
- When done: Ctrl+C here or run `/manual-check --stop` to kill servers
- Backend log: artifacts/test-runs/backend-manual-$PORT.log
```

### Section refinement checks (when study_pack.py changed)

- [ ] Submit a SHORT video (<5 min) — Study Guide should show sections WITHOUT "(Part N)" labels
- [ ] Submit a LONG lecture (>30 min) — Study Guide should show some sections WITH "(Part N)" labels
- [ ] Refined sections should have distinct timestamp ranges within the same chapter
- [ ] First sub-section of a split chapter should have a full bilingual summary
- [ ] Additional sub-sections should have English-only extracted text (no Chinese)
- [ ] Key points should be spread across sub-sections, not duplicated
- [ ] Export Markdown — verify "(Part N)" appears in the downloaded .md file
- [ ] Total section count should not exceed 10

### Study guide rendering checks (when StudyGuideView.tsx changed)

- [ ] No React key warnings in browser console (F12 → Console)
- [ ] Sections from the same chapter render as separate cards
- [ ] Timestamp ranges on each section card are correct (no overlaps)

## Step 6 — Suggest test URLs

Print 2-3 video URLs the user can paste, chosen to exercise different paths:

- A short video (~5 min): `https://www.youtube.com/watch?v=Lk_OQufs1HQ`
- A long lecture (~60 min): `https://www.youtube.com/live/1jU05MlENOI`
- The default bilibili video: `https://www.bilibili.com/video/BV1E8UQBeEzg`

## Stopping

If `$ARGUMENTS` contains `--stop`:
```bash
lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
lsof -ti :$FRONTEND_PORT | xargs kill -9 2>/dev/null || true
echo "Servers stopped."
```
Skip all other steps.

## Error handling

- If backend fails to start: show last 30 lines of log
- If frontend fails: show vite error output
- If ports are in use after kill: warn and suggest alternate ports
- Never leave zombie processes — always attempt cleanup on failure
