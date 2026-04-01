"""
Group individual emails into thread groups before passing to the triage agent.
Each thread group represents a conversation (same account + thread_id).
"""

import logging
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

# Max messages to show the agent per thread (oldest are dropped to save tokens)
MAX_MESSAGES_PER_THREAD = 3


def _parse_date(date_str: str):
    """Parse email date string to datetime, return epoch 0 on failure."""
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(0, tz=timezone.utc)


def group_threads(emails: list[dict]) -> list[dict]:
    """
    Group emails by (account, thread_id) into thread groups.

    Returns a list of thread group dicts, each containing:
    - thread_id, account
    - messages: list of emails (newest-first, max MAX_MESSAGES_PER_THREAD)
    - all_email_ids: every message ID in this thread (for guardrails completeness check)
    - total_message_count: full thread length before truncation
    """
    # Bucket emails by (account, thread_id)
    buckets: dict[tuple, list[dict]] = {}
    for email in emails:
        key = (email['account'], email['thread_id'])
        buckets.setdefault(key, []).append(email)

    thread_groups = []
    for (account, thread_id), msgs in buckets.items():
        # Sort newest-first
        msgs.sort(key=lambda m: _parse_date(m['date']), reverse=True)

        all_ids = [m['id'] for m in msgs]
        total = len(msgs)

        # Keep at most MAX_MESSAGES_PER_THREAD for the agent
        shown = msgs[:MAX_MESSAGES_PER_THREAD]

        # Mark the latest message
        for i, m in enumerate(shown):
            m['is_thread_latest'] = (i == 0)

        thread_groups.append({
            'thread_id': thread_id,
            'account': account,
            'messages': shown,
            'all_email_ids': all_ids,
            'total_message_count': total,
        })

    # Sort thread groups: most-recently-active first (newest message date)
    thread_groups.sort(
        key=lambda g: _parse_date(g['messages'][0]['date']),
        reverse=True,
    )

    logger.info(
        f"Grouped {len(emails)} emails into {len(thread_groups)} thread groups "
        f"({sum(1 for g in thread_groups if g['total_message_count'] > 1)} multi-message threads)"
    )
    return thread_groups


def build_agent_payload(thread_groups: list[dict]) -> list[dict]:
    """
    Convert thread groups into a compact JSON-serialisable payload for the agent.
    Strips fields not needed for classification to minimise token usage.
    """
    payload = []
    for group in thread_groups:
        msgs = []
        for m in group['messages']:
            # Truncate account to local part (sn10019, shreyn, etc.) — saves tokens
            account_short = m['account'].split('@')[0]
            msgs.append({
                'id': m['id'],
                'account': account_short,
                'from': f"{m['sender']} <{m['sender_email']}>",
                'subject': m['subject'],
                'date': m['date_simple'],   # pre-formatted short date
                'snippet': m['snippet'][:150],
                'labels': m.get('labels_filtered', []),
                'has_attachment': m.get('has_attachment', False),
                'is_thread_latest': m.get('is_thread_latest', True),
                'is_likely_automated': m.get('is_likely_automated', False),
            })

        entry = {
            'thread_id': group['thread_id'],
            'email_ids': group['all_email_ids'],
            'message_count': group['total_message_count'],
            'messages': msgs,
        }
        if group['total_message_count'] > MAX_MESSAGES_PER_THREAD:
            entry['thread_note'] = (
                f"{group['total_message_count']} total messages; "
                f"oldest {group['total_message_count'] - MAX_MESSAGES_PER_THREAD} omitted."
            )
        payload.append(entry)

    return payload
