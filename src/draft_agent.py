"""
Create Gmail draft replies for eligible Tier 1 emails.
Drafts are placed in the receiving account's draft box for user review — never auto-sent.
"""

import base64
import email.message
import logging
import os
import re

import anthropic
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Categories where we never draft (pay bill / accept invite — not email replies)
NO_DRAFT_CATEGORIES = {'calendar_conflicts', 'payments_due'}

# Secondary automated sender guard (belt-and-suspenders on top of guardrails)
_AUTOMATED_RE = re.compile(
    r'^(noreply|no-reply|no_reply|donotreply|do-not-reply|do_not_reply|'
    r'mailer-daemon|postmaster|bounce|bounces|notifications?|alerts?)@',
    re.IGNORECASE,
)

# Content signals that indicate "do not reply"
_DNR_PHRASES = [
    'do not reply', 'do not respond', 'this mailbox is not monitored',
    'please do not reply', 'not a monitored mailbox', 'unmonitored inbox',
    'automated message', 'automated email', 'this is an automated',
]


def _load_draft_prompt() -> str:
    path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'draft_reply.txt')
    with open(path, encoding='utf-8') as f:
        return f.read()


def _get_gmail_service(config: dict, account_email: str):
    """Get Gmail service for the account that received the email."""
    accounts = config['gmail']['accounts']
    account_cfg = next((a for a in accounts if a['email'] == account_email), None)
    if not account_cfg:
        raise ValueError(f"No config found for account {account_email}")

    abs_path = os.path.join(os.path.dirname(__file__), '..', account_cfg['token_path'])
    scopes = config['gmail']['scopes']
    creds = Credentials.from_authorized_user_file(abs_path, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(abs_path, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)


def _is_dnr_content(snippet: str) -> bool:
    """Check snippet for 'do not reply' phrases."""
    lower = snippet.lower()
    return any(phrase in lower for phrase in _DNR_PHRASES)


def _generate_draft_text(email_data: dict, config: dict) -> str:
    """Call Haiku to generate a 2-4 sentence draft reply body."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    prompt_template = _load_draft_prompt()
    prompt = prompt_template.format(
        personal_context=config.get('personal_context', ''),
        sender_name=email_data.get('sender', ''),
        sender_email=email_data.get('sender_email', ''),
        subject=email_data.get('subject', ''),
        snippet=email_data.get('snippet', ''),
        summary=email_data.get('summary', ''),
        suggested_action=email_data.get('suggested_action', ''),
    )

    model = config.get('agent', {}).get('model', 'claude-haiku-4-5-20251001')
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=300,
        temperature=0.3,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return message.content[0].text.strip()


def _create_gmail_draft(service, email_data: dict, draft_text: str) -> dict:
    """
    Push draft to Gmail using the Drafts API.
    Includes In-Reply-To and References headers so it threads correctly.
    """
    msg = email.message.EmailMessage()
    msg['To'] = email_data.get('sender_email', '')
    msg['Subject'] = f"Re: {email_data.get('subject', '')}"

    msg_id_header = email_data.get('message_id_header', '')
    if msg_id_header:
        msg['In-Reply-To'] = msg_id_header
        msg['References'] = msg_id_header

    msg.set_content(draft_text)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    draft_body = {'message': {'raw': raw}}
    # Attach to the existing Gmail thread so the draft shows in the right conversation
    thread_id = email_data.get('thread_id', '')
    if thread_id:
        draft_body['message']['threadId'] = thread_id

    result = service.users().drafts().create(userId='me', body=draft_body).execute()
    return result


def create_drafts(scored_emails: list[dict], config: dict) -> dict:
    """
    For each eligible Tier 1 email, generate a draft reply and push to Gmail.

    Returns dict of {email_id: draft_info} for emails where a draft was created.
    Only processes thread-representative emails to avoid duplicate drafts per thread.
    """
    drafts_cfg = config.get('drafts', {})
    if not drafts_cfg.get('enabled', True):
        logger.info("Draft creation disabled in config.")
        return {}

    max_drafts = drafts_cfg.get('max_per_run', 5)
    no_draft_cats = set(drafts_cfg.get('no_draft_categories', NO_DRAFT_CATEGORIES))
    no_draft_senders = [s.lower() for s in drafts_cfg.get('no_draft_senders', [])]

    # Only consider representative emails (one per thread) that are draft-eligible
    candidates = [
        e for e in scored_emails
        if e.get('draft_eligible')
        and e.get('is_thread_representative')
        and e['tier'] == 1
        and e['category'] not in no_draft_cats
    ]

    # Sort by priority score descending so most urgent get drafts first
    candidates.sort(key=lambda x: -x['priority_score'])

    drafts_created = {}

    for email_data in candidates[:max_drafts]:
        email_id = email_data['email_id']
        sender_email = email_data.get('sender_email', '')

        # Check configurable no_draft_senders list (exact or @domain match)
        sender_lower = sender_email.lower()
        if any(
            sender_lower == s or (s.startswith('@') and sender_lower.endswith(s))
            for s in no_draft_senders
        ):
            logger.info(f"Skipped draft (no_draft_senders config): {sender_email}")
            continue

        # Belt-and-suspenders: re-check automated sender signals
        if _AUTOMATED_RE.match(sender_email):
            logger.info(f"Skipped draft (automated address): {sender_email}")
            continue
        if email_data.get('is_likely_automated'):
            logger.info(f"Skipped draft (automated sender flag): {sender_email}")
            continue
        if _is_dnr_content(email_data.get('snippet', '')):
            logger.info(f"Skipped draft (do-not-reply content): {email_data.get('subject', '')}")
            continue

        try:
            draft_text = _generate_draft_text(email_data, config)
            service = _get_gmail_service(config, email_data['account'])
            result = _create_gmail_draft(service, email_data, draft_text)
            draft_id = result.get('id', '')

            drafts_created[email_id] = {
                'draft_id': draft_id,
                'draft_text': draft_text,
                'account': email_data['account'],
                'to': sender_email,
                'subject': f"Re: {email_data.get('subject', '')}",
            }
            logger.info(
                f"Draft created [{email_data['account']}] "
                f"to {sender_email}: {email_data.get('subject', '')[:50]}"
            )

        except Exception as e:
            logger.error(f"Draft creation failed for {email_id}: {e}")

    logger.info(f"Drafts created: {len(drafts_created)}/{len(candidates)} eligible")
    return drafts_created
