# FindJob : « Mes candidatures »

> 🇫🇷 **Tu veux l'utiliser pour toi ?** Suis le guide pas à pas : [INSTALLATION.md](INSTALLATION.md)
> (copie du dépôt, ta clé Gemini, ton profil, installation sur ton PC Windows).

## Business France Scraper (VIE)

Automatically scrapes [Business France VIE](https://mon-vie-via.businessfrance.fr/)
offers, filters them against **your** profile using Google Gemini, and sends
you a Telegram message for each relevant one — running by itself on GitHub
Actions, with a live metrics dashboard.

**No server**, **no code** to write. You fork the repo, add a few settings, and it
runs on a schedule in the cloud.

---

## What it does

Every run, the watcher:

1. **Scrapes** the latest VIE offers from Business France (the last 14 days).
2. **Filters** any offers it hasn't seen before, asking Gemini whether each
   one matches the profile you describe (e.g. *"data scientist: Python, SQL,
   statistics, machine learning"*).
3. **Notifies** you on Telegram about the offers judged relevant — with the
   title, company, location, and a direct link.
4. **Remembers** every offer it has already checked, so you're never notified
   twice, and only genuinely new offers are ever sent.

It runs on weekdays, several times (depends on Github's traffic) between 08:00 and 20:00 Paris time, and
publishes a dashboard tracking how many offers it scraped, how many were
relevant, and whether anything went wrong.

---

## Setup

Everything below is done in your browser and the GitHub settings screens —
there is no code to edit.

### 1. Fork this repository

Click **Fork** (top right of the repo page) to create your own copy. All the
steps below happen in **your** fork.

### 2. Reset the data files

This repo commits its own running data back into itself, so your fresh fork
inherits my offers and run history. Reset both files so
your watcher starts clean and judges offers against *your* profile.

- **`data/offers.json`** — replace the entire contents with exactly:
  ```
  {}
  ```
  (Two characters, not blank)

- **`docs/metrics.jsonl`** — delete all its contents, leaving the file
  completely empty.

You can edit both directly on GitHub (open the file → pencil icon → edit →
commit). This matters because inherited offers already carry a
"checked" verdict and would be skipped; resetting forces every offer to be
re-judged against your own profile.

### 3. Get your API keys and IDs

You need three secret values and one preference:

**Gemini API key** — a free key from
[Google AI Studio](https://aistudio.google.com/apikey). Sign in, create a
key, copy it.

**Telegram bot token** — message [@BotFather](https://t.me/BotFather) on
Telegram, send `/newbot`, follow the prompts, and copy the token it gives you
(looks like `123456:ABC-DEF...`).

**Telegram chat ID** — send any message to your new bot first, then open this
URL in a browser (replacing `<TOKEN>` with your bot token):
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Find the `"chat":{"id": ...}` value in the response — that number is your
chat ID. (The bot can't message you until you've messaged it at least once.)

**Your profile** — a description of your profile to match the offers appropriately.
Feel free to make it as detailed as needed based on the relevance of the offers you receive on Telegram.
For example, mine includes:
- degree or educational background
- description of the types of positions I'm looking for
- technical skills
- languages

### 4. Add secrets and your profile to GitHub

In your fork: **Settings → Secrets and variables → Actions**.

Under the **Secrets** tab, add three (**New repository secret**):

| Name                  | Value                        |
|-----------------------|------------------------------|
| `GEMINI_API_KEY`      | your Gemini key              |
| `TELEGRAM_BOT_TOKEN`  | your bot token               |
| `TELEGRAM_CHAT_ID`    | your chat ID                 |

Under the **Variables** tab, add one (**New repository variable**):

| Name               | Value             |
|--------------------|-------------------|
| `USER_DESCRIPTION` | your profile |

### 5. Enable Actions and run the watcher

1. Go to the **Actions** tab. If prompted, click to enable workflows for your
   fork.
2. Select **VIE Watcher** in the left sidebar.
3. Click **Run workflow** to start it manually the first time.

The first run does a full backfill of the last 14 days — it checks several
hundred offers and can take a while (Gemini's free tier is rate-limited, so
the watcher paces itself and may spread the backfill across a couple of runs).
You'll receive Telegram messages for any relevant offers it finds.

After this, it runs on its own — weekdays, roughly hourly, 08:00–20:00 Paris
time — and each later run only checks the handful of new offers since the last
one.

### 6. Set up the schedule with cron-job.org

GitHub's own `schedule:` trigger is unreliable — runs are frequently delayed
by hours or dropped entirely when GitHub is under load. In practice an
"hourly" schedule often delivers only one or two runs a day.

The fix is to let an external scheduler trigger the workflow through GitHub's
API. [cron-job.org](https://cron-job.org) is free, fires on time, and lets you
set the schedule directly in Paris time (so daylight saving is handled for
you).

**a. Create a GitHub token**

GitHub → **Settings → Developer settings → Personal access tokens →
Fine-grained tokens → Generate new token**:

- **Repository access:** Only select repositories → your fork
- **Permissions:** Repository permissions → **Actions: Read and write**
  (the only permission needed)
- **Expiration:** set one, and note the date — when it lapses the scheduler
  stops silently

Copy the token immediately; GitHub only shows it once.

**b. Create the cron job**

Sign up at cron-job.org, then **Create cronjob**:

**URL** (replace with your username and repo name):
```
https://api.github.com/repos/<username>/<repo>/actions/workflows/watch.yml/dispatches
```

**Schedule** — select the custom execution schedule tick and under "Expression Crontab" enter: 7 8-20 * * 1-5.

**Advanced settings:**

- **Timezone:** Chose the right one for you
- **Request method:** `POST`
- **Request body:**
  ```json
  {"ref":"main"}
  ```
- **Headers:**
  ```
  Accept: application/vnd.github+json
  Authorization: Bearer <your-token>
  X-GitHub-Api-Version: 2022-11-28
  Content-Type: application/json
  User-Agent: vie-watcher-cron
  ```

Leave the "HTTP authentication" user/password fields **empty** — the
`Authorization` header handles authentication.

The `User-Agent` header is easy to miss but **required**: GitHub rejects API
requests without one, returning `403 Forbidden`.

**c. Test it**

Hit **Test run**. Success is **`204 No Content`** — GitHub returns an empty
body on a successful dispatch, so "no content" is correct, not an error. A new
run should appear in your Actions tab within seconds.

If you get `401`, the token is wrong or missing the `Bearer ` prefix. `403` is
usually the missing `User-Agent`, or a token without *Actions: Read and write*.
`404` usually means the workflow filename in the URL doesn't match
`.github/workflows/watch.yml`.

Runs triggered this way show as **"Manually run by \<you\>"** in the Actions
tab rather than "Scheduled" — that's normal.

### 7. Enable the dashboard (optional)

To see the metrics dashboard:

1. **Settings → Pages**.
2. Source: **Deploy from a branch**, Branch: `main`, folder: `/docs`, then
   **Save**.
3. After a minute, the page URL appears at the top — something like
   `https://<your-username>.github.io/<repo-name>/`.

---

## Monitoring

**Telegram** — you receive a message per relevant offer, and a "run failed"
alert if a run breaks, so you always know the watcher is alive.

**Dashboard** — the Pages URL shows, per run: new offers scraped, relevant
offers, offers left unchecked, errors, and run time, plus a table of every
run. Open or refresh it any time; it reflects the latest committed data.

**Logs** — for detail on any run, go to the **Actions** tab, click a run, and
expand the steps to see the full log (which offers were checked, any errors,
etc.).

---

## Stopping or pausing the watcher

**Found a job? Pause it:** go to the **Actions** tab → **VIE Watcher** in the
sidebar → the **⋯** menu (or "Disable workflow" button) → **Disable
workflow**. This stops all scheduled runs immediately — no more messages. It's
fully reversible: an **Enable workflow** button appears in the same place if
you want it back later.

**Stop it permanently:** disabling as above is usually enough, but you can
also delete the repository entirely (**Settings → Delete this repository**).

Note: GitHub automatically disables scheduled workflows in public repos after
60 days of no activity, so a forgotten watcher eventually stops on its own.

---

## How it works (for the curious)

- **`src/scraper.py`** — pulls offers from the Business France API, stopping
  once it reaches offers it already knows about.
- **`src/relevance.py`** + **`src/gemini_handler.py`** — ask Gemini to judge
  each new offer, with automatic retries and rotation between Gemini models
  when rate limits are hit.
- **`src/telegram.py`** — formats and sends the notifications.
- **`src/store.py`** — remembers every offer (in `data/offers.json`) so
  nothing is checked or sent twice, and drops offers older than 14 days.
- **`src/metrics.py`** — records one line per run to `docs/metrics.jsonl`,
  which the dashboard reads.
- **`src/main.py`** — ties it together and enforces the weekday/daytime
  schedule.
- **`.github/workflows/watch.yml`** — runs it all on GitHub's servers on a
  schedule and commits the updated data back.

---

## Notes and limitations

- **Gemini free tier** caps daily requests (around 500–1000/day across the
  models used). The one-time backfill can approach this; normal hourly runs
  use very little. If a run hits the limit, it stops cleanly and resumes on
  the next run — no offers are lost.
- **GitHub's scheduler is best-effort.** Scheduled runs can be delayed or
  occasionally skipped under load, so "hourly" is approximate (often closer to 2-3 hours between runs). For catching
  VIE offers this is enough.
- **The Business France API key** in the config is the public one embedded in
  their website — it's the same for everyone and not a secret.

---

# CDI Watcher (HelloWork + LinkedIn)

A second watcher lives in this repo next to the VIE one. It searches **CDI**
offers on HelloWork and LinkedIn, asks Gemini whether each new offer fits the
profile, and sends a Telegram message per relevant offer with:

- title, company, location, contract, source and a direct link;
- why it matches, and **which CV to send** (your CVs are listed in the
  `candidat` block of `cdi_search.yaml`);
- a **cover-letter draft** in a copyable block, to proofread before applying.

It never applies by itself: you open the link and apply.

## Setup (once)

1. **Profile** — add a repository **secret** named `CDI_USER_DESCRIPTION`
   (Settings → Secrets and variables → Actions → New repository secret) with
   your profile in French: education, experience, skills, languages, the kinds
   of jobs you want. If it is missing, the watcher falls back to
   `USER_DESCRIPTION`.
2. Nothing else: it reuses `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN` and
   `TELEGRAM_CHAT_ID`, and it starts automatically after each VIE Watcher run
   (so the cron-job.org schedule drives both).
3. First test: Actions tab → **CDI Watcher** → **Run workflow** (a manual run
   ignores the hour restriction).

## Tuning — `cdi_search.yaml`

Edit it directly on GitHub: keywords, words that exclude a title (stage,
alternance, senior...), max offer age, run hours (default 9h, 13h, 18h Paris
time on weekdays), region, Gemini models, and whether to draft letters.

## Files

- `src/sources/hellowork.py`, `src/sources/linkedin.py` — scrapers (public
  pages only, no login, a few seconds between requests).
- `src/cdi_relevance.py` — Gemini prompts (verdict + CV choice, letter draft).
- `src/cdi_main.py` — orchestration, Telegram messages.
- `data/cdi_offers.json` — offers already seen (letters and descriptions are
  not kept), `docs/cdi_metrics.jsonl` — one line per run.

## Limits

- LinkedIn often blocks requests coming from GitHub's servers. When that
  happens the run logs "blocked", skips LinkedIn and still processes HelloWork.
- The scrapers read the sites' HTML: if a site redesigns its pages, a scraper
  may return 0 offers until its selectors are updated.
- Automated collection may go against the sites' terms of use; the watcher
  keeps volume low (a few searches, three times a day).
