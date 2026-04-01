"""
Unit tests for src/thread_grouper.py — pure Python, no LLM calls.
Run: python -m pytest tests/test_thread_grouper.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from thread_grouper import group_threads, MAX_MESSAGES_PER_THREAD


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_email(id: str, account: str, thread_id: str, date: str, subject: str = 'Test') -> dict:
    """Return a minimal email dict suitable for group_threads."""
    return {
        'id': id,
        'account': account,
        'thread_id': thread_id,
        'date': date,
        'date_simple': date[:6],
        'sender': 'Alice',
        'sender_email': 'alice@example.com',
        'subject': subject,
        'snippet': 'snippet text',
        'has_attachment': False,
        'is_likely_automated': False,
        'list_unsubscribe': '',
        'message_id_header': '',
        'labels_filtered': [],
    }


# RFC 2822-style dates for reliable sorting
DATE_OLD   = 'Mon, 01 Jan 2026 08:00:00 +0000'
DATE_MID   = 'Tue, 02 Jan 2026 08:00:00 +0000'
DATE_NEW   = 'Wed, 03 Jan 2026 08:00:00 +0000'
DATE_NEWER = 'Thu, 04 Jan 2026 08:00:00 +0000'


# ── Same (account, thread_id) grouping ─────────────────────────────────────────

def test_same_account_same_thread_grouped():
    emails = [
        _make_email('e1', 'user@gmail.com', 'thread_A', DATE_OLD),
        _make_email('e2', 'user@gmail.com', 'thread_A', DATE_NEW),
    ]
    groups = group_threads(emails)
    assert len(groups) == 1
    group = groups[0]
    assert group['thread_id'] == 'thread_A'
    assert group['account'] == 'user@gmail.com'
    assert set(group['all_email_ids']) == {'e1', 'e2'}


def test_different_threads_produce_different_groups():
    emails = [
        _make_email('e1', 'user@gmail.com', 'thread_A', DATE_OLD),
        _make_email('e2', 'user@gmail.com', 'thread_B', DATE_NEW),
    ]
    groups = group_threads(emails)
    assert len(groups) == 2
    thread_ids = {g['thread_id'] for g in groups}
    assert thread_ids == {'thread_A', 'thread_B'}


def test_single_email_forms_own_group():
    emails = [_make_email('e1', 'user@gmail.com', 'thread_X', DATE_NEW)]
    groups = group_threads(emails)
    assert len(groups) == 1
    assert groups[0]['all_email_ids'] == ['e1']
    assert groups[0]['total_message_count'] == 1


def test_empty_input_returns_empty_list():
    assert group_threads([]) == []


# ── Different accounts stay separate even if same thread_id ───────────────────

def test_same_thread_id_different_accounts_are_separate():
    emails = [
        _make_email('e1', 'alice@gmail.com', 'shared_thread', DATE_OLD),
        _make_email('e2', 'bob@gmail.com',   'shared_thread', DATE_NEW),
    ]
    groups = group_threads(emails)
    assert len(groups) == 2
    accounts = {g['account'] for g in groups}
    assert accounts == {'alice@gmail.com', 'bob@gmail.com'}
    # Each group has exactly one email
    for g in groups:
        assert len(g['all_email_ids']) == 1


def test_same_thread_id_same_account_combined():
    emails = [
        _make_email('e1', 'alice@gmail.com', 'shared_thread', DATE_OLD),
        _make_email('e2', 'alice@gmail.com', 'shared_thread', DATE_NEW),
    ]
    groups = group_threads(emails)
    assert len(groups) == 1
    assert set(groups[0]['all_email_ids']) == {'e1', 'e2'}


# ── Thread truncation to MAX_MESSAGES_PER_THREAD ──────────────────────────────

def test_thread_truncated_to_max_messages():
    emails = [
        _make_email(f'e{i}', 'user@gmail.com', 'thread_T',
                    f'Mon, 0{i+1} Jan 2026 08:00:00 +0000')
        for i in range(5)
    ]
    groups = group_threads(emails)
    assert len(groups) == 1
    group = groups[0]
    assert len(group['messages']) == MAX_MESSAGES_PER_THREAD
    assert group['total_message_count'] == 5
    assert len(group['all_email_ids']) == 5  # all IDs preserved


def test_thread_under_max_not_truncated():
    emails = [
        _make_email('e1', 'user@gmail.com', 'thread_S', DATE_OLD),
        _make_email('e2', 'user@gmail.com', 'thread_S', DATE_NEW),
    ]
    groups = group_threads(emails)
    assert len(groups[0]['messages']) == 2
    assert groups[0]['total_message_count'] == 2


def test_all_email_ids_preserved_after_truncation():
    """all_email_ids must contain every message even if messages list is truncated."""
    emails = [
        _make_email(f'e{i}', 'user@gmail.com', 'thread_TR',
                    f'Mon, 0{i+1} Jan 2026 08:00:00 +0000')
        for i in range(5)
    ]
    groups = group_threads(emails)
    group = groups[0]
    assert len(group['all_email_ids']) == 5
    assert len(group['messages']) == MAX_MESSAGES_PER_THREAD


# ── Newest message gets thread_latest: True ────────────────────────────────────

def test_newest_message_flagged_as_thread_latest():
    emails = [
        _make_email('e_old',   'user@gmail.com', 'thread_L', DATE_OLD),
        _make_email('e_mid',   'user@gmail.com', 'thread_L', DATE_MID),
        _make_email('e_new',   'user@gmail.com', 'thread_L', DATE_NEW),
    ]
    groups = group_threads(emails)
    group = groups[0]
    # messages are newest-first
    assert group['messages'][0]['id'] == 'e_new'
    assert group['messages'][0].get('is_thread_latest') is True


def test_only_newest_message_flagged_as_latest():
    emails = [
        _make_email('e_old', 'user@gmail.com', 'thread_M', DATE_OLD),
        _make_email('e_new', 'user@gmail.com', 'thread_M', DATE_NEW),
    ]
    groups = group_threads(emails)
    group = groups[0]
    latest_flags = [m.get('is_thread_latest', False) for m in group['messages']]
    assert sum(latest_flags) == 1
    assert group['messages'][0].get('is_thread_latest') is True


def test_single_message_thread_is_latest():
    emails = [_make_email('e1', 'user@gmail.com', 'thread_1', DATE_NEW)]
    groups = group_threads(emails)
    assert groups[0]['messages'][0].get('is_thread_latest') is True


# ── Oldest message is dropped when truncating ─────────────────────────────────

def test_oldest_message_dropped_when_truncating():
    """When 4 messages exist, the oldest should not appear in group['messages']."""
    emails = [
        _make_email('e_oldest', 'user@gmail.com', 'thread_D', DATE_OLD),
        _make_email('e_mid',    'user@gmail.com', 'thread_D', DATE_MID),
        _make_email('e_new',    'user@gmail.com', 'thread_D', DATE_NEW),
        _make_email('e_newest', 'user@gmail.com', 'thread_D', DATE_NEWER),
    ]
    groups = group_threads(emails)
    group = groups[0]
    shown_ids = {m['id'] for m in group['messages']}
    assert 'e_oldest' not in shown_ids
    assert 'e_newest' in shown_ids


def test_oldest_id_still_in_all_email_ids_after_drop():
    """Even though oldest is dropped from messages, it must remain in all_email_ids."""
    emails = [
        _make_email('e_oldest', 'user@gmail.com', 'thread_DA', DATE_OLD),
        _make_email('e_mid',    'user@gmail.com', 'thread_DA', DATE_MID),
        _make_email('e_new',    'user@gmail.com', 'thread_DA', DATE_NEW),
        _make_email('e_newest', 'user@gmail.com', 'thread_DA', DATE_NEWER),
    ]
    groups = group_threads(emails)
    group = groups[0]
    assert 'e_oldest' in group['all_email_ids']


# ── messages list is ordered newest-first ─────────────────────────────────────

def test_messages_newest_first():
    emails = [
        _make_email('e_old', 'user@gmail.com', 'thread_O', DATE_OLD),
        _make_email('e_mid', 'user@gmail.com', 'thread_O', DATE_MID),
        _make_email('e_new', 'user@gmail.com', 'thread_O', DATE_NEW),
    ]
    groups = group_threads(emails)
    dates = [m['date'] for m in groups[0]['messages']]
    assert dates == [DATE_NEW, DATE_MID, DATE_OLD]


# ── total_message_count ────────────────────────────────────────────────────────

def test_total_message_count_accurate():
    n = 7
    emails = [
        _make_email(f'e{i}', 'user@gmail.com', 'thread_C',
                    f'Mon, 0{i+1} Jan 2026 08:00:00 +0000')
        for i in range(n)
    ]
    groups = group_threads(emails)
    assert groups[0]['total_message_count'] == n


# ── Multiple threads mixed together ───────────────────────────────────────────

def test_multiple_threads_mixed_emails():
    emails = [
        _make_email('a1', 'user@gmail.com', 'thread_A', DATE_OLD),
        _make_email('b1', 'user@gmail.com', 'thread_B', DATE_MID),
        _make_email('a2', 'user@gmail.com', 'thread_A', DATE_NEW),
        _make_email('c1', 'user@gmail.com', 'thread_C', DATE_NEWER),
    ]
    groups = group_threads(emails)
    assert len(groups) == 3

    by_thread = {g['thread_id']: g for g in groups}
    assert set(by_thread['thread_A']['all_email_ids']) == {'a1', 'a2'}
    assert by_thread['thread_B']['all_email_ids'] == ['b1']
    assert by_thread['thread_C']['all_email_ids'] == ['c1']
