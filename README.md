# Morning Brief — Automated Email Triage & Daily Digest

An automated system that reads your Gmail every morning, classifies and prioritizes emails using AI, and delivers a formatted digest to your inbox (+ optional Telegram push notification).

## Quick Start (15 minutes)

### 1. Prerequisites
- Python 3.11+
- A Gmail account (your other email accounts should forward here)
- One of:
  - **Ollama** installed locally with `llama3.1:8b` (free, recommended)
  - **Anthropic API key** (Haiku: ~$0.03/month, Sonnet: ~$0.30/month)

### 2. Install Dependencies

```bash
cd email-triage
pip install -r requirements.txt
```

### 3. Set Up Gmail API (OAuth2 — Free)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable the **Gmail API**: APIs & Services → Library → search "Gmail API" → Enable
4. Create OAuth2 credentials:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: **Desktop app**
   - Download the JSON file
5. Save it as `credentials/client_secret.json`
6. Run the auth flow once:

```bash
python src/auth_setup.py
```

This opens a browser window. Sign in, grant read-only access, and the token is saved to `credentials/token.json`.

### 4. Configure

Edit `config.yaml`:
- Set your email address under `delivery.gmail.send_to`
- Choose your LLM backend (`ollama` or `anthropic`)
- If using Anthropic, set your API key as an environment variable:
  ```bash
  export ANTHROPIC_API_KEY="sk-ant-..."
  ```
- (Optional) Set up Telegram bot — see instructions in config.yaml comments
- Customize `sender_overrides` with your priority contacts

### 5. Test Run

```bash
python src/main.py
```

This fetches the last 24 hours of email, classifies everything, and delivers your digest.

### 6. Schedule (Cron)

```bash
# Run the installer script
chmod +x cron_setup.sh
./cron_setup.sh
```

Or manually add to crontab:
```bash
crontab -e
# Add this line (10 AM PT = 5 PM UTC during PDT):
0 17 * * * cd /path/to/email-triage && /usr/bin/python3 src/main.py >> logs/morning-brief.log 2>&1
```

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Gmail API   │ ──▶ │   Classify   │ ──▶ │    Score     │ ──▶ │   Deliver    │
│  (OAuth2)    │     │  (LLM/Rules) │     │  (Rubric)    │     │ (Email/TG)   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

## Cost

| Component | Monthly Cost |
|-----------|-------------|
| Gmail API | Free |
| Ollama + Llama 3.1 | Free (local) |
| OR Haiku API | ~$0.03/month |
| OR Sonnet API | ~$0.30/month |
| Gmail SMTP delivery | Free |
| Telegram Bot | Free |

## File Structure

```
email-triage/
├── config.yaml              # All configuration
├── requirements.txt         # Python dependencies
├── cron_setup.sh           # Crontab installer
├── credentials/            # OAuth tokens (gitignored)
│   ├── client_secret.json
│   └── token.json
├── src/
│   ├── main.py             # Orchestrator
│   ├── auth_setup.py       # One-time OAuth setup
│   ├── fetch_emails.py     # Gmail API fetcher
│   ├── classify.py         # LLM classification
│   ├── score.py            # Priority scoring + overrides
│   ├── format_digest.py    # HTML digest formatter
│   └── deliver.py          # Email/Telegram sender
├── prompts/
│   └── classify_prompt.txt # Classification prompt
├── templates/
│   └── digest.html         # Jinja2 email template
├── tests/
│   └── test_classify.py    # Unit tests
└── logs/                   # Runtime logs
```

## Troubleshooting

- **"Token expired"**: Delete `credentials/token.json` and re-run `python src/auth_setup.py`
- **Ollama not responding**: Ensure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3.1:8b`)
- **Gmail API quota**: Free tier allows 10,000 requests/day — more than enough
- **Emails missing**: Check that your other email accounts are forwarding to Gmail (Settings → Accounts and Import)
