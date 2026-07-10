# TPF Community Bot — Community Intelligence Assistant

A small Flask service for **The Product Folks** Slack community. The bot is an
**assistant, not an autonomous actor**: it watches Slack and reports to a
designated **community handler** (the Human POC). It never messages members,
never replies in a public channel, and never moderates on its own — the handler
decides what to do.

It does three things:

**1. Daily report** (on demand, `/tasks/daily-report`) — one DM covering the
last 24h:

1. **New members** who joined (so the handler can welcome them **personally**).
2. **Who said what** — per channel, the noteworthy messages with attribution.
3. **Might need a reply** — unanswered questions/requests.
4. **Looks out of place** — messages that don't fit their channel.

**2. Real-time new-member alert** — the moment someone joins, the handler gets a
DM with their name, mention, Slack ID, join time and workspace.

**3. Real-time channel moderation** — every channel message is judged against
its channel's stated purpose. If it doesn't belong, the handler gets a private
DM with the original message, the reasoning, a suggested channel, a
copy-paste-ready reply, and a confidence score. **If it belongs, nothing
happens at all** — no notification, no reply, no storage.

> Understanding uses **OpenAI when `OPENAI_API_KEY` is set** (`ai.py`), and falls
> back to keyword heuristics otherwise (`analysis.py` + the `redirects` in
> `channel_rules.py`). The bot keeps working with no API key at all.

---

## How it works

```
                          POST /slack/events
                                  │
                    verify signature, dedupe event id
                                  │
                    ┌─────────────┴──────────────┐
                    │   200 OK returned NOW      │  ← Slack's 3s budget is safe
                    └─────────────┬──────────────┘
                                  │ handlers.dispatch → background.py (thread pool)
                 ┌────────────────┴─────────────────┐
     team_join   │                                  │  message
                 ▼                                  ▼
      store.record_member()              filters: bot? subtype? DM?
                 │                       too short? thread reply?
                 ▼                                  │
     🎉 DM handler (templates.py)                   ▼
                                        moderation.evaluate()
                                    ai.moderate_message()  ──fail──▶  heuristics
                                                │                     (channel_rules
                                                ▼                      redirects →
                                        belongs? ──yes──▶ do nothing    analysis.py)
                                                │
                                                no + confidence ≥ threshold
                                                ▼
                                    ⚠️ DM handler (templates.py)

Daily report (unchanged):
GET/POST /tasks/daily-report → collect.py (live history) → ai.py / analysis.py
        → build_digest + format_daily_report → DM the handler
```

| File | Role |
| ---- | ---- |
| `app.py` | Flask app: verify, dedupe, enqueue, task endpoints. No business logic. |
| `handlers.py` | What to do with each event (join → alert; message → moderate). |
| `background.py` | Thread pool so AI + DM work never blocks the Slack ack. |
| `moderation.py` | Decides *whether* a message belongs. AI first, heuristics on failure. |
| `channel_rules.py` | **Channel purposes and rules. The only file you edit to add a channel.** |
| `ai.py` | OpenAI: batched report classification + real-time moderation prompt. |
| `notify.py` | `notify_handler(...)`, DM delivery with retry, cached name lookups. |
| `templates.py` | The DM wording (new-member alert, moderation alert). |
| `retry.py` | Shared backoff helper (honours Slack's `Retry-After`). |
| `config.py` | All env-driven settings + the shared Slack client. |
| `analysis.py` | Keyword heuristics + daily report builder/formatter. |
| `collect.py` | Fetches recent channel history live at report time. |
| `store.py` | Tiny SQLite store recording who joined (for the report). |
| `slack_verify.py` | Verifies the Slack request signature (signing secret + HMAC). |

### Adding a channel

Edit `channel_rules.py` only — no application logic changes:

```python
"design": {
    "purpose": "Design critique and UX feedback.",
    "allowed": ["Design critique", "UX feedback"],
    "not_allowed": ["Job postings", "Promotions"],
    "redirects": [                       # keyword fallback, used only when AI is down
        {"suggested_channel": "#jobs", "reason": "advertising a job opportunity",
         "phrases": ("we are hiring", "job opening")},
    ],
}
```

Channels with no entry are **not moderated** unless
`MODERATE_UNCONFIGURED_CHANNELS=on`. The AI may only ever suggest a channel that
exists in this file — hallucinated channel names are dropped.

---

## 1. Slack app configuration

### OAuth scopes
In **OAuth & Permissions → Bot Token Scopes**, add:

- `chat:write` — DM the POC
- `im:write` — open the DM channel with the POC
- `channels:join` — join all public channels (`/tasks/join-public`)
- `channels:history`, `groups:history` — read channel history for the report
- `channels:read`, `groups:read` — list/resolve channel names
- `users:read` — resolve member names
- `team:read` — receive `team_join` (new member) events

Reinstall the app after changing scopes, then copy the **Bot User OAuth Token**
(`xoxb-...`).

### Signing secret
From **Basic Information → App Credentials**, copy the **Signing Secret**.

### Event subscriptions
Under **Event Subscriptions**:

1. Enable events and set the **Request URL** to
   `https://<your-app>.onrender.com/slack/events` (the app answers Slack's
   `url_verification` automatically — it should show **Verified**).
2. Under **Subscribe to bot events**, add:
   - **`team_join`** — new member joined (daily report + real-time alert)
   - **`message.channels`** — public channel messages (real-time moderation)
   - **`message.groups`** — private channel messages (real-time moderation)
3. Save (reinstall if prompted).

> Without `message.channels` / `message.groups` the daily report still works,
> but real-time moderation never fires — Slack simply won't deliver the events.

> The bot reads history only for channels it's a member of — run
> `/tasks/join-public` (below) so it joins them all.

---

## 2. Environment variables

```bash
cp .env.example .env
```

| Variable                          | Description                                                        |
| --------------------------------- | ------------------------------------------------------------------ |
| `SLACK_BOT_TOKEN`                 | Bot User OAuth Token (`xoxb-...`)                                  |
| `SLACK_SIGNING_SECRET`            | App signing secret (request verification)                          |
| `HANDLER_SLACK_USER`              | Slack user ID (`U...`) of the handler who gets **all** DMs         |
| `HUMAN_POC_USER_ID`               | Legacy name for the same person; used if `HANDLER_SLACK_USER` unset |
| `DIGEST_TRIGGER_TOKEN`            | Shared secret protecting the `/tasks/*` endpoints                  |
| `DAILY_WINDOW_HOURS`              | Hours of history the report covers (default `24`)                  |
| `OPENAI_API_KEY`                  | *(optional)* enables AI classification **and** AI moderation       |
| `OPENAI_MODEL`                    | OpenAI model (default `gpt-4o-mini`)                               |
| `AI_CLASSIFICATION`               | `on`/`off` toggle even when a key is set (default `on`)            |
| `REALTIME_MEMBER_ALERTS`          | DM the handler on each join (default `on`)                         |
| `MODERATION_ENABLED`              | Real-time channel moderation (default `on`)                        |
| `MODERATION_CONFIDENCE_THRESHOLD` | Minimum confidence to alert, `0.0`–`1.0` (default `0.7`)           |
| `MODERATION_MIN_CHARS`            | Skip messages shorter than this (default `15`)                     |
| `MODERATE_UNCONFIGURED_CHANNELS`  | Moderate channels missing from `channel_rules.py` (default `off`)  |
| `MODERATE_THREAD_REPLIES`         | Moderate replies inside threads (default `off`)                    |
| `AI_MAX_RETRIES`                  | Retries before falling back to heuristics (default `2`)            |
| `SLACK_MAX_RETRIES`               | Attempts per Slack write (default `3`)                             |
| `BACKGROUND_WORKERS`              | Threads for off-request AI/DM work (default `4`)                   |
| `DB_PATH`                         | SQLite file path (default `bot_data.db`)                           |
| `PORT`                            | Local port (optional; Render sets this)                            |

> **Handler user ID:** in Slack, open the person's profile → **⋮** → **Copy member ID**.

---

## 3. Run locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Expose it to Slack with a tunnel (e.g. [ngrok](https://ngrok.com/)):

```bash
ngrok http 3000
```

Use `https://<id>.ngrok.io/slack/events` as the Request URL while testing.

---

## 4. Task endpoints

Both are protected by `DIGEST_TRIGGER_TOKEN` (pass `?token=...`); if the token
isn't set they're open (testing only).

**Join all public channels** — run once after install, and again when new public
channels are added:

```bash
curl "http://localhost:3000/tasks/join-public?token=YOUR_TOKEN"
```
Private channels can't be self-joined — an admin must invite the bot to those.

**Daily report** — builds the report and DMs it to the POC:

```bash
curl "http://localhost:3000/tasks/daily-report?token=YOUR_TOKEN"
```
Returns a small JSON summary and DMs the full report. It's **not automated
yet** — once proven out, hit it on a schedule (Render Cron, cron-job.org, or a
local launchd/cron job on a Mac) once a day.

---

## 5. Deploy to Render

This repo includes a `render.yaml` Blueprint.

1. Push to a Git repository.
2. In Render: **New → Blueprint**, select the repo.
3. Set the environment variables (`SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`,
   `HANDLER_SLACK_USER`, `DIGEST_TRIGGER_TOKEN`, and `OPENAI_API_KEY` if using AI).
4. After deploy, set the Slack **Request URL** to
   `https://<your-app>.onrender.com/slack/events`, add the `message.channels` /
   `message.groups` event subscriptions, and run `/tasks/join-public`.

No new dependencies were added — `requirements.txt` is unchanged.

Manual setup (without the Blueprint):

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app --timeout 120`

> ⚠️ **Keep gunicorn on one worker** (the default). Each worker process gets its
> own background thread pool and its own event-dedupe cache, so running several
> workers means a Slack retry delivered to a different worker could be processed
> twice. If you need more capacity, raise `BACKGROUND_WORKERS`, not `--workers`.

> **Render free tier sleeps.** A sleeping instance misses events entirely —
> Slack gets no ack and eventually gives up. Real-time alerts need a paid
> instance (or a pinger); the daily report is unaffected because it re-reads
> history on demand.

> ℹ️ **No message storage.** The report fetches history live from Slack, so a
> wiped disk loses nothing. The only local state is the small "who joined" list
> for the new-members section; if it's wiped, that section may miss recent
> joins. Point `DB_PATH` at a persistent disk to avoid that.

---

## Design decisions

- **Human-in-the-loop:** the bot only reports to the handler. It never welcomes,
  replies, corrects, or moderates — the handler does all user-facing actions.
  Moderation alerts are **private DMs**; nothing is ever posted in the channel.
- **No message storage:** moderation reads the event and discards it. The daily
  report pulls the last day from Slack at run time (`collect.py`). The only
  persisted data is each member's join time.
- **Fast acks:** `/slack/events` verifies, dedupes and returns 200 immediately;
  AI calls and DMs run on a background thread pool (`background.py`). Slack's
  3-second budget is never at risk.
- **AI with a safety net:** with `OPENAI_API_KEY` set, `ai.py` judges channel fit
  semantically. On any failure (rate limit, outage, bad JSON) `moderation.py`
  falls back to the `channel_rules` keyword redirects, then to `analysis.py`.
  Either way the bot only *flags candidates*.
- **Confidence gating:** only verdicts at or above
  `MODERATION_CONFIDENCE_THRESHOLD` (default `0.7`) reach the handler. Weak
  keyword guesses score `0.6` on purpose — they inform the daily report but
  don't page anyone in real time.
- **No hallucinated channels:** a suggested channel is dropped unless it exists
  in `channel_rules.py`, so the handler is never told to redirect someone to a
  channel that doesn't exist.
- **Noise control:** bot posts, message edits/joins, DMs to the bot, thread
  replies and very short messages are never moderated.
- **Already-answered filter:** a question isn't flagged "needs a reply" if it
  already has thread replies (`reply_count`).
- **Signature verification:** every `/slack/events` request is validated with a
  constant-time HMAC; requests older than 5 minutes are rejected. Event IDs are
  deduped in a bounded cache so Slack retries are handled once.

---

## Tuning moderation

Too many alerts? Raise `MODERATION_CONFIDENCE_THRESHOLD` (e.g. `0.85`), or
tighten the channel's `not_allowed` list. Missing things? Lower it to `0.6`, and
make the channel's `purpose` more specific — the AI judges against that sentence
more than anything else.

Every decision is logged, including the ones that *didn't* alert:

```
moderation_verdict channel=general source=ai belongs=False confidence=0.95 suggested=#jobs
moderation_no_action channel=general belongs=True confidence=0.90 threshold=0.70 duration_ms=812
moderation_alerted channel=general author=U123 source=ai confidence=0.95 suggested=#jobs duration_ms=1042
notify_handler title='⚠️ Channel Moderation Alert' priority=high delivered=True
```

---

## Roadmap

- **Scheduling:** automate the daily report once trusted (Render Cron / Mac).
- **Reply from the DM:** let the handler send the suggested reply with one click
  (Slack interactive buttons) instead of copy-paste.
- **Per-channel thresholds:** a stricter bar in `#announcements` than in
  `#general`.
