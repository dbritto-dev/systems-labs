"""The screen, in English. Every language has the same names and {placeholders} (a test checks)."""

# ---- the window
TOO_SMALL = "The terminal is {cols}x{rows}; this needs at least {min_cols}x{min_rows} ({best} looks best). Make the window bigger."
PAUSED = "paused"
SIMULATING = "simulating"
LOADING = "loading"
STOPPED = "stopped"
BEHAVIOR = "Behavior:"
STAGE_AT = "Your stage shows at {clock}, once the first incident is judged · ↑ speeds up"
EDIT_AND_SAVE = "Edit {file} and save: this window reruns it."
ERROR = "error: {error}"
MENU = {"pause": "pause/resume", "restart": "restart", "rerun": "rerun", "view": "view", "quit": "quit"}
VIEW = "view: {name}"  # shown when a lab has more than one picture
HUD = "frame {ms:.1f} ms · {fps:.0f} fps · drew {drawn}/{ticks} · {ahead:.0f} s ahead"  # key d
VIEWS = {"lanes": "lanes", "cluster": "cluster", "relay": "relay", "fanout": "fan-out", "peers": "peers"}
VIEWS = {"lanes": "lanes", "cluster": "cluster", "relay": "relay", "fanout": "fan-out", "fanin": "fan-in"}
VIEWS = {"lanes": "lanes", "cluster": "cluster", "relay": "relay", "fanout": "fan-out", "pipeline": "pipeline"}
NO_VIEW = "{lab} has no {name!r} view (it has: {views})"

# ---- the picture: the state under the server or the cluster
STATES = {"healthy": "HEALTHY", "down": "DOWN", "degraded": "DEGRADED", "busy": "BUSY",
          "overloaded": "OVERLOADED", "connected": "CONNECTED", "partitioned": "PARTITIONED"}

# ---- loading and errors
STARTING = "Starting {title}"
STEP_PROCESS = "Started a Python process for your code"
STEP_LOADED = "Loaded {file}"
STEP_SIMULATING = "Simulating the first minute on a virtual clock"
STEP_WHAT = "users arrive, things go wrong at random, goals are judged"
WHILE_YOU_WAIT = "While you wait"
WATCH_FOR = "Watch for: {text}"
STILL_SIMULATING = "Still simulating after {seconds} s: a slow loop in your code? It is stopped at 20 s."
STOPPED_WITH_ERROR = "Your code stopped with an error"
EDIT = "Edit"
FIX_AND_SAVE = "Fix it and save: this window reruns it."
EDIT_HERE = "edit {where}"  # after an error message: (edit labs/x/main.py:12)
RUN_CRASHED = "the run crashed (exit code {code})"
NO_RESULT = "no result after {seconds} s, so it was stopped. Is there an endless loop (a retry loop without a limit)?"

# ---- status line
RUNNING_YOUR_CODE = "running your code…"
LOADING_YOUR_CODE = "loading your code"
SIMULATING_FIRST_MINUTE = "simulating the first minute"
RERAN_AT = "{reason} at {clock}: playing from 0:00"
REASONS = {"reran": "reran", "restarted": "restarted"}

# ---- the panel
STATS = {"served": "served", "failed": "failed", "waiting": "waiting", "p50": "p50", "p99": "p99"}
USERS = "Users"
WAITS = "waits: last 5 s"
CALLS = "Calls"
PER_SECOND = "per second, last 1 s"
EVENTS = "Events"
SO_FAR = "{n} so far"
NONE_YET = "none yet"
NEXT = "NEXT"
STATUS = {"ok": "OK", "alert": "ALERT", "wait": "WAIT"}
COUNTS = {"ok": "{n} OK", "alert": "{n} ALERT", "wait": "{n} WAIT"}
PHASES = {"before": "before", "during": "during", "after": "after"}
VERBS = {"alert": "ALERT", "ok": "OK", "warn": "WARN"}  # up to 6 letters

# ---- goals and incidents
NEXT_FIRST_RUN = "waiting for the first run"
NEXT_INCIDENT = "waiting for {incident}"  # incident: "the next outage"
NEXT_AT_START = "{rule}: judged when {incident} starts"  # incident: "the outage"
NEXT_AT_END = "{rule}: judged when {incident} ends"
NEXT_AFTER = "{rule}: judged after {incident}"
# the same, short, for when the line above does not fit the panel
NEXT_AT_START_SHORT = "{rule} · at start"
NEXT_AT_END_SHORT = "{rule} · at end"
NEXT_AFTER_SHORT = "{rule} · after"
NEXT_INCIDENT_SHORT = "{incident}"
INCIDENT_TITLE = "{name} #{n}"
STARTED = "started"
ENDED = "ended"

# ---- the command line
LABS_HEADER = "Labs (watch one with: uv run python -m live <lab>)"
NO_LAB = "no lab named {name!r}. Labs: {labs}"
LESSON = {"learn": "Learn", "watch": "Watch for", "build": "In production", "checklist": "Checklist",
          "refs": "Read more", "next": "Try next"}
