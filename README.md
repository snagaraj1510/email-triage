# Morning Brief — Email Triage

> **Why I built this:** Managing multiple inboxes during an active job search meant spending 20–30 minutes every morning just triaging email — figuring out what actually needed attention versus what could wait. I wanted a system that would apply the same prioritization logic I'd use manually, but automatically, before I even opened my laptop. So I built a pipeline that reads across all my accounts, classifies every email by urgency and consequence using Claude, and pushes a ranked digest to my inbox and Telegram each morning.

Reads your Gmail every morning, classifies and prioritizes emails using an AI agent, and delivers a formatted digest to your inbox and Telegram. Runs automatically via GitHub Actions — no laptop required.

## Features

- **Multi-account Gmail** — fetches from up to 4 Gmail accounts in one digest
- **Agentic triage** — single Claude Haiku call reasons holistically across all threads; escalates to Sonnet on failure
- **4-tier priority system** — weighted rubric across urgency, consequence, relationship, and effort
- **Guardrails** — validates agent output, strips hallucinated IDs, applies rule-based fallback if the agent fails entirely
- **Draft replies** — generates up to 5 draft replies per run for Tier 1 emails, pushed to Gmail Drafts (never auto-sent)
- **Sender history** — tracks frequent Tier 4 senders across runs, surfaces unsubscribe candidates, feeds context back into triage
- **Weekly rollup** — Sunday digest summarizing the week's inbox patterns
- **Dual delivery** — HTML email digest + Telegram push notification
- **Runs in the cloud** — GitHub Actions triggers at 9am ET daily, no laptop needed

## Priority Tiers

| Tier | Label | Categories |
|------|-------|---------|
| T1 | Action Required Today | deadlines_due_dates, payments_due, calendar_conflicts, time_sensitive_replies |
| T2 | Important — Act This Week | job_search_recruiting, professional_networking, financial_account_alerts, property_management |
| T3 | Awareness | newsletters_industry_news, personal_correspondence, academic_mba, receipts_confirmations |
| T4 | Low Priority / Noise | marketing_promotions, automated_notifications, spam_unsubscribe_candidates |

## Pipeline

```
fetch_emails      → Pull last 24h from up to 4 Gmail accounts (metadata + snippet)
thread_grouper    → Group emails into conversation threads (newest-first, max 3 msgs shown)
triage_agent      → Claude Haiku classifies all threads in one call; Sonnet fallback on failure
guardrails        → Validate tiers/categories/scores; strip hallucinated IDs; rule-based fallback for missing threads
draft_agent       → Generate 2–4 sentence draft replies for eligible T1 emails → push to Gmail Drafts
sender_history    → Update T4 sender frequency; feed top-30 back into next run's agent prompt
format_digest     → Build HTML email + Telegram summary
deliver           → Send via Gmail + Telegram (or save locally)
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/snagaraj1510/email-triage.git
cd email-triage
pip install -r requirements.txt
```

### 2. Set up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Enable the **Gmail API**: APIs & Services → Library → search "Gmail API" → Enable
3. Create OAuth credentials: APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app
4. Download and save as `credentials/client_secret.json`
5. Authorize each Gmail account:

```bash
python src/auth_setup.py
```

This opens a browser for each account and saves tokens to `credentials/`.

### 3. Configure

Copy `config.example.yaml` to `config.yaml` and fill in:

```yaml
gmail:
  accounts:
    - email: "your@gmail.com"
      credentials_path: "credentials/client_secret.json"
      token_path: "credentials/token_1.json"

personal_context: |
  Describe your role and email priorities here — this is injected directly into
  the triage agent's system prompt. Be specific about what matters to you.
  Example: I'm job searching for Strategy/BizOps roles at tech companies.
  Recruiter emails and interview scheduling are top priority.
```

Set your API key: `export ANTHROPIC_API_KEY="sk-ant-..."`

### 4. Test locally

```bash
python src/main.py --dry-run    # classify and print results, no delivery or drafts
python src/main.py --no-drafts  # full run, skip draft creation
python src/main.py --save-local # save HTML digest locally instead of emailing
python src/main.py              # full run
```

## GitHub Actions (Automated — Recommended)

The workflow runs at **9am ET daily** (two cron entries handle EST/EDT transitions).

### Required GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `CONFIG_YAML` | Full contents of your `config.yaml` |
| `GMAIL_TOKEN_1` | Contents of `credentials/token_1.json` (first account) |
| `GMAIL_TOKEN_2` | Contents of token file for second account (if used) |
| `GMAIL_TOKEN_3` | Contents of token file for third account (if used) |
| `GMAIL_TOKEN_4` | Contents of token file for fourth account (if used) |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/botfather) on Telegram |
| `TELEGRAM_CHAT_ID` | From [@userinfobot](https://t.me/userinfobot) on Telegram |
| `SENDER_HISTORY` | Leave blank on first run; auto-updated by the workflow each run |
| `GH_PAT` | GitHub Personal Access Token with `secrets:write` scope (needed to persist `SENDER_HISTORY`) |

The workflow maps `GMAIL_TOKEN_1/2/3/4` to token file paths automatically based on your `config.yaml` account order.

### Manual trigger

Go to Actions → Morning Brief → **Run workflow** to send a briefing on demand.

## Draft Replies

For eligible Tier 1 emails, the pipeline generates a short (2–4 sentence) draft reply and pushes it to Gmail Drafts — threaded correctly so it shows in the right conversation. Drafts are **never auto-sent**.

Control draft behavior in `config.yaml`:

```yaml
drafts:
  enabled: true
  max_per_run: 5
  no_draft_categories:
    - calendar_conflicts
    - payments_due
  no_draft_senders:           # Never draft to these (exact or @domain wildcard)
    - noreply@example.com
    - "@automated.com"
```

## File Structure

```
email-triage/
├── config.example.yaml           # Configuration template (copy to config.yaml)
├── requirements.txt
├── .github/workflows/
│   └── morning-brief.yml         # GitHub Actions schedule + secret restoration
├── credentials/                  # OAuth tokens (gitignored)
│   └── token_*.json
├── data/
│   └── sender_history.json       # Persisted T4 sender tracking (gitignored)
├── prompts/
│   ├── triage_system.txt         # Triage agent system prompt
│   └── draft_reply.txt           # Draft generation prompt
├── src/
│   ├── main.py                   # Pipeline orchestrator
│   ├── auth_setup.py             # One-time OAuth setup
│   ├── fetch_emails.py           # Gmail API fetcher
│   ├── thread_grouper.py         # Thread grouping logic
│   ├── triage_agent.py           # Agentic triage (Claude Haiku + Sonnet fallback)
│   ├── guardrails.py             # Output validation + rule-based fallback
│   ├── draft_agent.py            # Draft reply generation + Gmail Drafts API
│   ├── sender_history.py         # Sender frequency tracking + persistence
│   ├── format_digest.py          # HTML + Telegram formatter
│   ├── deliver.py                # Email + Telegram delivery
│   └── weekly_rollup.py          # Sunday weekly digest
└── tests/
    ├── test_guardrails.py        # 20 tests: tier clamping, fallback, validation
    ├── test_thread_grouper.py    # 15 tests: grouping, truncation, ordering
    └── test_sender_history.py    # 17 tests: tracking, pruning, prompt context
```

## Running Tests

```bash
pytest tests/ -v
```

## Troubleshooting

- **Token expired**: Delete the relevant `credentials/token_*.json` and re-run `python src/auth_setup.py`
- **No emails showing**: Check `fetch_window_hours` in `config.yaml` (default: 24 hours)
- **Telegram not sending**: Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
- **Agent returning malformed JSON**: Haiku retries twice then escalates to Sonnet; if all fail, rule-based fallback applies automatically
- **SENDER_HISTORY not persisting**: Ensure `GH_PAT` secret has `secrets:write` scope
