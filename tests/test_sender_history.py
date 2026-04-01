"""
Unit tests for src/sender_history.py — uses tempfile for all file I/O.
Run: python -m pytest tests/test_sender_history.py -v
"""

import sys
import os
import json
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
import sender_history as sh


# ── Helpers ────────────────────────────────────────────────────────────────────

def _empty_history() -> dict:
    return {'tier4_senders': {}, 'daily_stats': []}


def _scored_email(
    email_id: str = 'e1',
    tier: int = 4,
    sender: str = 'Promo Corp',
    sender_email: str = 'promo@example.com',
    is_thread_representative: bool = True,
    list_unsubscribe: str = '',
) -> dict:
    return {
        'email_id': email_id,
        'thread_id': 'thread_1',
        'account': 'user@gmail.com',
        'tier': tier,
        'sender': sender,
        'sender_email': sender_email,
        'subject': 'Big sale!',
        'date': 'Mon, 01 Apr 2026 08:00:00 +0000',
        'date_simple': 'Apr 1',
        'is_thread_representative': is_thread_representative,
        'list_unsubscribe': list_unsubscribe,
        'has_attachment': False,
        'is_likely_automated': True,
    }


def _run_update(history: dict, emails: list, drafts: dict = None) -> dict:
    """Thin wrapper around update_history with a sensible default for drafts."""
    return sh.update_history(history, emails, drafts or {})


# ── load / save round-trip (with tempfile) ─────────────────────────────────────

def test_load_missing_file_returns_empty_structure(tmp_path):
    path = str(tmp_path / 'nonexistent.json')
    original = sh.HISTORY_PATH
    sh.HISTORY_PATH = path
    try:
        result = sh.load_history()
        assert result == {'tier4_senders': {}, 'daily_stats': []}
    finally:
        sh.HISTORY_PATH = original


def test_save_and_reload_roundtrip(tmp_path):
    path = str(tmp_path / 'history.json')
    original = sh.HISTORY_PATH
    sh.HISTORY_PATH = path
    try:
        data = {'tier4_senders': {'a@b.com': {'display_name': 'A', 'count': 3,
                                               'last_seen': '2026-04-01',
                                               'list_unsubscribe': ''}},
                'daily_stats': []}
        sh.save_history(data)
        loaded = sh.load_history()
        assert loaded == data
    finally:
        sh.HISTORY_PATH = original


# ── Adding a new Tier 4 sender creates entry with count=1 ─────────────────────

def test_new_tier4_sender_creates_entry():
    history = _empty_history()
    emails = [_scored_email(sender_email='new@example.com', sender='New Sender')]
    history = _run_update(history, emails)
    assert 'new@example.com' in history['tier4_senders']
    entry = history['tier4_senders']['new@example.com']
    assert entry['count'] == 1
    assert entry['display_name'] == 'New Sender'


def test_new_tier4_sender_count_is_exactly_one():
    history = _empty_history()
    emails = [_scored_email(sender_email='once@example.com')]
    history = _run_update(history, emails)
    assert history['tier4_senders']['once@example.com']['count'] == 1


def test_non_tier4_sender_not_tracked():
    history = _empty_history()
    emails = [_scored_email(sender_email='boss@work.com', tier=1)]
    history = _run_update(history, emails)
    assert 'boss@work.com' not in history['tier4_senders']


def test_non_representative_email_not_counted():
    history = _empty_history()
    emails = [_scored_email(sender_email='promo@example.com', is_thread_representative=False)]
    history = _run_update(history, emails)
    assert 'promo@example.com' not in history['tier4_senders']


# ── Seeing same sender again increments count ──────────────────────────────────

def test_same_sender_increments_count():
    history = _empty_history()
    email = _scored_email(sender_email='repeat@example.com')

    history = _run_update(history, [email])
    assert history['tier4_senders']['repeat@example.com']['count'] == 1

    history = _run_update(history, [email])
    assert history['tier4_senders']['repeat@example.com']['count'] == 2


def test_same_sender_three_times_count_is_three():
    history = _empty_history()
    email = _scored_email(sender_email='triple@example.com')

    for _ in range(3):
        history = _run_update(history, [email])

    assert history['tier4_senders']['triple@example.com']['count'] == 3


def test_sender_email_stored_lowercase():
    history = _empty_history()
    emails = [_scored_email(sender_email='UPPER@Example.COM')]
    history = _run_update(history, emails)
    # key should be lowercased
    assert 'upper@example.com' in history['tier4_senders']


def test_last_seen_updated_on_second_appearance():
    history = _empty_history()
    email = _scored_email(sender_email='seen@example.com')

    history = _run_update(history, [email])
    first_seen = history['tier4_senders']['seen@example.com']['last_seen']

    history = _run_update(history, [email])
    second_seen = history['tier4_senders']['seen@example.com']['last_seen']

    # Both calls happen "today", so last_seen should equal today's date
    today = datetime.now().strftime('%Y-%m-%d')
    assert second_seen == today


# ── Pruning removes senders last seen > 60 days ago ───────────────────────────

def test_prune_removes_old_sender():
    history = _empty_history()
    old_date = (datetime.now() - timedelta(days=61)).strftime('%Y-%m-%d')
    history['tier4_senders']['old@example.com'] = {
        'display_name': 'Old Sender',
        'count': 5,
        'last_seen': old_date,
        'list_unsubscribe': '',
    }
    # update_history triggers pruning as a side effect
    history = _run_update(history, [])
    assert 'old@example.com' not in history['tier4_senders']


def test_prune_keeps_recent_sender():
    history = _empty_history()
    recent_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    history['tier4_senders']['recent@example.com'] = {
        'display_name': 'Recent Sender',
        'count': 2,
        'last_seen': recent_date,
        'list_unsubscribe': '',
    }
    history = _run_update(history, [])
    assert 'recent@example.com' in history['tier4_senders']


def test_prune_exactly_60_days_ago_is_kept():
    """Senders last seen exactly 60 days ago are on the boundary and should be kept."""
    history = _empty_history()
    boundary_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    history['tier4_senders']['boundary@example.com'] = {
        'display_name': 'Boundary',
        'count': 1,
        'last_seen': boundary_date,
        'list_unsubscribe': '',
    }
    history = _run_update(history, [])
    assert 'boundary@example.com' in history['tier4_senders']


def test_prune_61_days_ago_removed():
    history = _empty_history()
    old_date = (datetime.now() - timedelta(days=61)).strftime('%Y-%m-%d')
    history['tier4_senders']['stale@example.com'] = {
        'display_name': 'Stale',
        'count': 10,
        'last_seen': old_date,
        'list_unsubscribe': '',
    }
    history = _run_update(history, [])
    assert 'stale@example.com' not in history['tier4_senders']


def test_prune_mixed_keeps_only_recent():
    history = _empty_history()
    old_date    = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    recent_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')

    history['tier4_senders']['old@example.com'] = {
        'display_name': 'Old', 'count': 5, 'last_seen': old_date, 'list_unsubscribe': ''}
    history['tier4_senders']['recent@example.com'] = {
        'display_name': 'Recent', 'count': 2, 'last_seen': recent_date, 'list_unsubscribe': ''}

    history = _run_update(history, [])
    assert 'old@example.com' not in history['tier4_senders']
    assert 'recent@example.com' in history['tier4_senders']


# ── daily_stats appended ───────────────────────────────────────────────────────

def test_daily_stats_appended():
    history = _empty_history()
    history = _run_update(history, [])
    assert len(history['daily_stats']) == 1
    assert 'date' in history['daily_stats'][0]
    assert 'total' in history['daily_stats'][0]


# ── get_tier4_senders_for_prompt ───────────────────────────────────────────────

def test_get_tier4_senders_for_prompt_returns_top_n_by_count():
    """Returns top-N senders sorted by count descending."""
    history = _empty_history()
    history['tier4_senders'] = {
        'a@example.com': {'display_name': 'A', 'count': 1, 'last_seen': '2026-04-01', 'list_unsubscribe': ''},
        'b@example.com': {'display_name': 'B', 'count': 10, 'last_seen': '2026-04-01', 'list_unsubscribe': ''},
        'c@example.com': {'display_name': 'C', 'count': 5, 'last_seen': '2026-04-01', 'list_unsubscribe': ''},
        'd@example.com': {'display_name': 'D', 'count': 3, 'last_seen': '2026-04-01', 'list_unsubscribe': ''},
    }
    result = sh.get_tier4_senders_for_prompt(history, top_n=3)
    assert isinstance(result, str)
    # The top sender by count (B with 10) should appear first
    assert result.index('b@example.com') < result.index('c@example.com')
    assert result.index('c@example.com') < result.index('d@example.com')
    # The lowest count sender (a@example.com, count=1) should be excluded
    assert 'a@example.com' not in result


def test_get_tier4_senders_for_prompt_returns_empty_string_if_no_history():
    """Returns empty string when there are no tier4 senders."""
    history = _empty_history()
    result = sh.get_tier4_senders_for_prompt(history, top_n=5)
    assert result == ''


def test_get_tier4_senders_for_prompt_returns_string():
    history = _empty_history()
    history['tier4_senders'] = {
        'z@example.com': {'display_name': 'Z', 'count': 7, 'last_seen': '2026-04-01', 'list_unsubscribe': ''},
    }
    result = sh.get_tier4_senders_for_prompt(history, top_n=5)
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_tier4_senders_for_prompt_top_n_limits_results():
    history = _empty_history()
    for i in range(10):
        history['tier4_senders'][f'sender{i}@example.com'] = {
            'display_name': f'Sender {i}', 'count': i + 1,
            'last_seen': '2026-04-01', 'list_unsubscribe': ''}
    result = sh.get_tier4_senders_for_prompt(history, top_n=3)
    # Count how many email addresses appear in the output
    count = sum(1 for i in range(10) if f'sender{i}@example.com' in result)
    assert count <= 3


def test_get_tier4_senders_for_prompt_all_returned_when_fewer_than_top_n():
    history = _empty_history()
    history['tier4_senders'] = {
        'only@example.com': {'display_name': 'Only', 'count': 2,
                              'last_seen': '2026-04-01', 'list_unsubscribe': ''},
    }
    result = sh.get_tier4_senders_for_prompt(history, top_n=10)
    assert 'only@example.com' in result
