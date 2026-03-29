# Morning Brief — Email Triage

Reads your Gmail every morning, classifies and prioritizes emails using AI, and delivers a formatted digest to your inbox and Telegram. Runs automatically via GitHub Actions — no laptop required.

## Features

- **Multi-account Gmail** — fetches from up to 4 Gmail accounts in one digest
- **AI classification** — categorizes emails into 4 priority tiers using Claude (or Ollama locally)
- **Smart scoring** — weighted rubric across urgency, consequence, relationship, and effort
- **Sender overrides** — auto-escalate recruiters, hiring managers, and key contacts to Tier 1
- **Dual delivery** — HTML email digest + Telegram push notification
- **Runs in the cloud** — GitHub Actions triggers at 9am ET Mon-Fri, no laptop needed

## Priority Tiers

| Tier | Label | Examples |
|------|-------|---------|
| T1 | Action Required Today | Deadlines, payments due, calendar conflicts, time-sensitive replies |
| T2 | Important — Act This Week | Recruiting, financial alerts, networking, property management |
| T3 | Awareness | Newsletters, personal correspondence, receipts |
| T4 | Low Priority / Noise | Marketing, automated notifications, spam candidates |

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

Edit `config.yaml`:
- Add your Gmail accounts under `gmail.accounts`
- Set `delivery.gmail.send_to` to your primary email
- Choose LLM backend: `anthropic` (recommended) or `ollama`
- Set your Anthropic API key as an env var: `export ANTHROPIC_API_KEY="sk-ant-..."`
- Customize `sender_overrides` with priority contacts

### 4. Test locally

```bash
python src/main.py --dry-run   # classify without sending
python src/main.py             # full run with delivery
```

## GitHub Actions (Automated — Recommended)

The workflow runs at **9am ET Mon-Fri** automatically, handling EST/EDT transitions year-round.

### Required GitHub Secrets

Go to your repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/botfather) on Telegram |
| `TELEGRAM_CHAT_ID` | From [@userinfobot](https://t.me/userinfobot) on Telegram |
| `GMAIL_TOKEN_SN10019` | Contents of `credentials/token_sn10019.json` |
| `GMAIL_TOKEN_S_NAGARAJ1510` | Contents of `credentials/token_s_nagaraj1510.json` |
| `GMAIL_TOKEN_MULTISTAR1732` | Contents of `credentials/token_multistar1732.json` |
| `GMAIL_TOKEN_SHREYN_UMICH` | Contents of `credentials/token_shreyn_umich.json` |

### Manual trigger

Go to Actions → Morning Brief → **Run workflow** to send a briefing on demand.

## Using Ollama (Free, No API Key)

```bash
ollama pull llama3.1:8b
ollama serve
```

Set `llm.backend: ollama` in `config.yaml`. Note: Ollama only works for local runs, not GitHub Actions.

## File Structure

```
email-triage/
├── config.yaml              # All configuration
├── requirements.txt
├── .github/workflows/
│   └── morning-brief.yml    # GitHub Actions schedule
├── credentials/             # OAuth tokens (gitignored)
│   ├── client_secret.json
│   └── token_*.json
├── src/
│   ├── main.py              # Orchestrator
│   ├── auth_setup.py        # One-time OAuth setup
│   ├── fetch_emails.py      # Gmail API fetcher
│   ├── classify.py          # LLM classification
│   ├── score.py             # Priority scoring + overrides
│   ├── format_digest.py     # HTML digest formatter
│   └── deliver.py           # Email + Telegram sender
├── prompts/
│   └── classify_prompt.txt
└── logs/
```

## Troubleshooting

- **Token expired**: Delete the relevant `credentials/token_*.json` and re-run `python src/auth_setup.py`
- **No emails showing**: Check `fetch_window_hours` in `config.yaml` (default: 24 hours)
- **Telegram not sending**: Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
