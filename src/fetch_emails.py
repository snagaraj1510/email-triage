"""
Fetch emails from Gmail API using batch HTTP requests.
Returns structured, token-efficient email data for the triage agent.
"""

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import BatchHttpRequest

logger = logging.getLogger(__name__)

# Headers to fetch — only what the agent or draft feature needs
METADATA_HEADERS = [
    'From', 'Subject', 'Date', 'Message-ID',
    'List-Unsubscribe', 'Precedence', 'Auto-Submitted',
    'X-Auto-Response-Suppress', 'In-Reply-To',
]

# Gmail label categories used for filtering (drop internal labels)
MEANINGFUL_LABELS = {
    'IMPORTANT', 'CATEGORY_PROMOTIONS', 'CATEGORY_SOCIAL',
    'CATEGORY_UPDATES', 'CATEGORY_FORUMS',
}

# Automated sender signals for is_likely_automated detection
_AUTOMATED_ADDR_RE = re.compile(
    r'^(noreply|no-reply|no_reply|donotreply|do-not-reply|do_not_reply|'
    r'mailer-daemon|postmaster|bounce|bounces|notifications?|alerts?|'
    r'.*-noreply|.*\.noreply)@',
    re.IGNORECASE,
)
_AUTOMATED_DOMAINS = {
    'amazonses.com', 'sendgrid.net', 'mailgun.org', 'mandrillapp.com',
    'postmarkapp.com', 'mailchimp.com', 'constantcontact.com',
    'notifications.google.com', 'facebookmail.com',
}


def _get_gmail_service(config: dict, token_path: str):
    """Build authenticated Gmail API service."""
    abs_path = os.path.join(os.path.dirname(__file__), '..', token_path)
    scopes = config['gmail']['scopes']
    creds = Credentials.from_authorized_user_file(abs_path, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(abs_path, 'w') as f:
            f.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)


def _get_header(headers: list, name: str) -> str:
    """Get a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h['name'].lower() == name_lower:
            return h['value']
    return ''


def _format_date_simple(date_str: str) -> str:
    """Convert RFC 2822 date to compact format: 'Mar 30, 10:14 AM'."""
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime('%b %-d, %-I:%M %p')
    except Exception:
        return date_str[:16] if date_str else ''


def _is_automated_sender(sender_email: str, headers: list) -> bool:
    """Detect automated/bulk senders from address and headers."""
    addr = sender_email.lower()

    if _AUTOMATED_ADDR_RE.match(addr):
        return True

    domain = addr.split('@')[-1] if '@' in addr else ''
    if domain in _AUTOMATED_DOMAINS:
        return True

    # Header-based signals
    if _get_header(headers, 'List-Unsubscribe'):
        return True
    precedence = _get_header(headers, 'Precedence').lower()
    if precedence in ('bulk', 'list', 'junk'):
        return True
    auto_submitted = _get_header(headers, 'Auto-Submitted').lower()
    if auto_submitted and auto_submitted != 'no':
        return True
    if _get_header(headers, 'X-Auto-Response-Suppress'):
        return True

    return False


def _has_attachment(payload: dict) -> bool:
    """Check if any MIME part has a filename (attachment indicator)."""
    for part in payload.get('parts', []):
        if part.get('filename'):
            return True
        # Recurse into nested multipart
        if part.get('parts'):
            if _has_attachment(part):
                return True
    return False


def _fetch_messages_batch(service, msg_ids: list[str]) -> dict:
    """
    Fetch message metadata for a list of message IDs using Gmail batch API.
    Returns dict of {msg_id: message_resource}.
    Batches in groups of 100 (Gmail API limit).
    """
    results = {}
    errors = {}

    def _make_callback(mid):
        def callback(request_id, response, exception):
            if exception:
                errors[mid] = exception
                logger.warning(f"Batch fetch failed for {mid}: {exception}")
            else:
                results[mid] = response
        return callback

    # Process in chunks of 100 (Gmail batch API limit)
    for i in range(0, len(msg_ids), 100):
        chunk = msg_ids[i:i + 100]
        batch: BatchHttpRequest = service.new_batch_http_request()
        for mid in chunk:
            batch.add(
                service.users().messages().get(
                    userId='me',
                    id=mid,
                    format='metadata',
                    metadataHeaders=METADATA_HEADERS,
                ),
                callback=_make_callback(mid),
                request_id=mid,
            )
        batch.execute()

    if errors:
        logger.warning(f"Batch fetch had {len(errors)} error(s) out of {len(msg_ids)} messages")
    return results


def fetch_emails(config: dict) -> list[dict]:
    """
    Fetch emails from all configured Gmail accounts for the last N hours.

    Returns list of email dicts with fields:
        id, thread_id, account, sender, sender_email,
        subject, date, date_simple, snippet, labels_filtered,
        has_attachment, is_likely_automated, list_unsubscribe,
        message_id_header, in_reply_to
    """
    hours = config['gmail']['fetch_window_hours']
    max_results = config['gmail']['max_results']
    query = f'newer_than:{hours}h label:inbox'

    all_emails = []

    for account in config['gmail']['accounts']:
        account_email = account['email']
        token_path = account['token_path']
        logger.info(f"Fetching for {account_email}")

        try:
            service = _get_gmail_service(config, token_path)
        except Exception as e:
            logger.warning(f"Auth failed for {account_email}: {e}")
            continue

        # ── List message IDs ──
        msg_refs = []
        page_token = None
        while len(msg_refs) < max_results:
            batch_size = min(100, max_results - len(msg_refs))
            try:
                result = service.users().messages().list(
                    userId='me', q=query,
                    maxResults=batch_size, pageToken=page_token,
                ).execute()
            except Exception as e:
                logger.warning(f"messages.list failed for {account_email}: {e}")
                break

            msgs = result.get('messages', [])
            if not msgs:
                break
            msg_refs.extend(msgs)
            page_token = result.get('nextPageToken')
            if not page_token:
                break

        if not msg_refs:
            logger.info(f"No messages found for {account_email}")
            continue

        logger.info(f"Found {len(msg_refs)} messages for {account_email} — fetching details via batch")

        # ── Batch fetch full metadata ──
        msg_ids = [m['id'] for m in msg_refs]
        fetched = _fetch_messages_batch(service, msg_ids)

        for mid, msg in fetched.items():
            try:
                headers = msg.get('payload', {}).get('headers', [])
                sender_raw = _get_header(headers, 'From')
                sender_name, sender_email = parseaddr(sender_raw)

                # Filter labels to meaningful set only
                labels_filtered = [
                    lbl for lbl in msg.get('labelIds', [])
                    if lbl in MEANINGFUL_LABELS
                ]

                list_unsub = _get_header(headers, 'List-Unsubscribe')
                # Extract the first URL or mailto from the header value
                unsub_match = re.search(r'<([^>]+)>', list_unsub)
                list_unsub_clean = unsub_match.group(1) if unsub_match else list_unsub.strip()

                email_data = {
                    'id': msg['id'],
                    'thread_id': msg.get('threadId', ''),
                    'account': account_email,
                    'sender': sender_name or sender_email,
                    'sender_email': sender_email.lower(),
                    'subject': _get_header(headers, 'Subject'),
                    'date': _get_header(headers, 'Date'),
                    'date_simple': _format_date_simple(_get_header(headers, 'Date')),
                    'snippet': unescape(msg.get('snippet', ''))[:150],
                    'labels_filtered': labels_filtered,
                    'has_attachment': _has_attachment(msg.get('payload', {})),
                    'is_likely_automated': _is_automated_sender(sender_email.lower(), headers),
                    'list_unsubscribe': list_unsub_clean,
                    'message_id_header': _get_header(headers, 'Message-ID'),
                    'in_reply_to': _get_header(headers, 'In-Reply-To'),
                }
                all_emails.append(email_data)
            except Exception as e:
                logger.warning(f"Failed to parse message {mid}: {e}")

        logger.info(f"Parsed {len(fetched)} emails for {account_email}")

    logger.info(f"Total emails fetched: {len(all_emails)} across {len(config['gmail']['accounts'])} accounts")
    return all_emails
