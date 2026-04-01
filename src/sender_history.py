"""
Track sender frequency and daily stats across runs.
Persists to data/sender_history.json, committed back to the repo by the workflow.
Powers the unsubscribe candidate feature (10a) and weekly rollup (10c).
"""

import json
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

HISTORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'sender_history.json')
MAX_DAILY_ENTRIES = 90  # keep 90 days of daily stats


def load_history() -> dict:
    """Load sender history from disk. Returns empty structure if file missing."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    if not os.path.exists(HISTORY_PATH):
        return {'tier4_senders': {}, 'daily_stats': []}
    try:
        with open(HISTORY_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load sender history: {e} — starting fresh")
        return {'tier4_senders': {}, 'daily_stats': []}


def save_history(history: dict):
    """Persist sender history to disk."""
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)
    logger.info("Sender history saved.")


def update_history(history: dict, scored_emails: list[dict], drafts_created: dict) -> dict:
    """
    Update history with today's run data.
    Only counts thread-representative emails to avoid inflating counts for multi-message threads.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    representative = [e for e in scored_emails if e.get('is_thread_representative')]

    # ── Update Tier 4 sender appearances ──
    tier4 = [e for e in representative if e['tier'] == 4]
    for email in tier4:
        key = email['sender_email'].lower()
        if not key:
            continue
        if key not in history['tier4_senders']:
            history['tier4_senders'][key] = {
                'display_name': email['sender'],
                'count': 0,
                'last_seen': today,
                'list_unsubscribe': email.get('list_unsubscribe', ''),
            }
        entry = history['tier4_senders'][key]
        entry['count'] += 1
        entry['last_seen'] = today
        entry['display_name'] = email['sender']
        # Update unsubscribe link if we have one
        if email.get('list_unsubscribe'):
            entry['list_unsubscribe'] = email['list_unsubscribe']

    # ── Prune Tier 4 senders not seen in 60 days ──
    cutoff = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    history['tier4_senders'] = {
        k: v for k, v in history['tier4_senders'].items()
        if v['last_seen'] >= cutoff
    }

    # ── Append today's daily stats ──
    tier_counts = {str(t): sum(1 for e in representative if e['tier'] == t) for t in (1, 2, 3, 4)}
    history['daily_stats'].append({
        'date': today,
        'total': len(representative),
        'tiers': tier_counts,
        'drafts_created': len(drafts_created),
    })

    # Trim to MAX_DAILY_ENTRIES
    history['daily_stats'] = history['daily_stats'][-MAX_DAILY_ENTRIES:]

    return history


def get_persistent_unsubscribe_candidates(history: dict, min_appearances: int = 3) -> list[dict]:
    """
    Return Tier 4 senders that have appeared at least min_appearances times.
    Sorted by appearance count descending.
    """
    candidates = [
        v for v in history['tier4_senders'].values()
        if v['count'] >= min_appearances
    ]
    candidates.sort(key=lambda x: x['count'], reverse=True)
    return candidates[:10]


def get_weekly_stats(history: dict) -> list[dict]:
    """Return the last 7 days of daily stats for the weekly rollup."""
    cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    return [s for s in history['daily_stats'] if s['date'] >= cutoff]


def get_tier4_senders_for_prompt(history: dict, top_n: int = 30) -> str:
    """Return a formatted string of frequent Tier 4 senders for the agent system prompt."""
    tier4 = history.get('tier4_senders', {})
    if not tier4:
        return ''
    sorted_senders = sorted(tier4.items(), key=lambda x: x[1].get('count', 0), reverse=True)[:top_n]
    lines = ['Frequent Tier 4 senders (auto-deprioritize unless content changes):']
    for sender, data in sorted_senders:
        lines.append(f"  - {sender} (seen {data.get('count', 1)}x)")
    return '\n'.join(lines)
