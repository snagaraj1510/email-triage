"""
Fetch emails from Gmail API for the configured time window.
Returns structured email data for classification.
"""

import base64
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from html import unescape

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def _get_gmail_service(config: dict, token_path: str):
    """Build authenticated Gmail API service for the given token_path."""
    abs_token_path = os.path.join(os.path.dirname(__file__), '..', token_path)
    scopes = config['gmail']['scopes']

    creds = Credentials.from_authorized_user_file(abs_token_path, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(abs_token_path, 'w') as f:
            f.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def _strip_html(html: str) -> str:
    """Extract readable text from HTML email body."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_body(payload: dict, max_chars: int = 500) -> str:
    """Extract text body from Gmail message payload."""
    body_text = ""
    
    if 'parts' in payload:
        for part in payload['parts']:
            mime_type = part.get('mimeType', '')
            if mime_type == 'text/plain' and 'data' in part.get('body', {}):
                raw = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                body_text = raw
                break
            elif mime_type == 'text/html' and 'data' in part.get('body', {}):
                raw = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                body_text = _strip_html(raw)
            elif mime_type.startswith('multipart/'):
                # Recurse into nested multipart
                nested = _extract_body(part, max_chars)
                if nested:
                    body_text = nested
    elif 'body' in payload and 'data' in payload['body']:
        raw = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
        if payload.get('mimeType') == 'text/html':
            body_text = _strip_html(raw)
        else:
            body_text = raw
    
    return body_text[:max_chars].strip()


def _get_header(headers: list, name: str) -> str:
    """Get a header value by name."""
    for h in headers:
        if h['name'].lower() == name.lower():
            return h['value']
    return ""


def fetch_emails(config: dict) -> list[dict]:
    """
    Fetch emails from all configured Gmail accounts for the last N hours.

    Returns list of dicts:
    {
        'id': str,
        'thread_id': str,
        'account': str,
        'sender': str,
        'sender_email': str,
        'subject': str,
        'date': str,
        'snippet': str,
        'body_preview': str,
        'labels': list[str],
        'has_attachment': bool
    }
    """
    hours = config['gmail']['fetch_window_hours']
    max_results = config['gmail']['max_results']
    query = f"newer_than:{hours}h label:inbox"

    all_emails = []

    for account in config['gmail']['accounts']:
        account_email = account['email']
        token_path = account['token_path']
        logger.info(f"Fetching emails for account: {account_email}")

        try:
            service = _get_gmail_service(config, token_path)
        except Exception as e:
            logger.warning(f"Failed to build Gmail service for {account_email}: {e}")
            continue

        logger.info(f"Fetching emails: query='{query}', max={max_results}")

        all_messages = []
        page_token = None

        while len(all_messages) < max_results:
            batch_size = min(100, max_results - len(all_messages))
            result = service.users().messages().list(
                userId='me',
                q=query,
                maxResults=batch_size,
                pageToken=page_token
            ).execute()

            messages = result.get('messages', [])
            if not messages:
                break

            all_messages.extend(messages)
            page_token = result.get('nextPageToken')
            if not page_token:
                break

        logger.info(f"Found {len(all_messages)} messages for {account_email}")

        # Fetch full details for each message
        for msg_ref in all_messages:
            try:
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_ref['id'],
                    format='full'
                ).execute()

                headers = msg.get('payload', {}).get('headers', [])
                sender_raw = _get_header(headers, 'From')
                sender_name, sender_email = parseaddr(sender_raw)

                email_data = {
                    'id': msg['id'],
                    'thread_id': msg.get('threadId', ''),
                    'account': account_email,
                    'sender': sender_name or sender_email,
                    'sender_email': sender_email.lower(),
                    'subject': _get_header(headers, 'Subject'),
                    'date': _get_header(headers, 'Date'),
                    'snippet': unescape(msg.get('snippet', '')),
                    'body_preview': _extract_body(msg.get('payload', {})),
                    'labels': msg.get('labelIds', []),
                    'has_attachment': any(
                        p.get('filename') for p in msg.get('payload', {}).get('parts', [])
                        if p.get('filename')
                    ),
                }
                all_emails.append(email_data)

            except Exception as e:
                logger.warning(f"Failed to fetch message {msg_ref['id']} for {account_email}: {e}")

        logger.info(f"Successfully fetched email details for {account_email}")

    logger.info(f"Total emails fetched across all accounts: {len(all_emails)}")
    return all_emails
