"""
Unit tests for src/guardrails.py — pure Python, no LLM calls.
Run: python -m pytest tests/test_guardrails.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from guardrails import _validate_tier_result, _rule_based_fallback, validate_and_flatten, VALID_CATEGORIES


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_thread_result(tier=1, category='time_sensitive_replies', priority_score=75,
                        thread_id='t1', email_ids=None, draft_eligible=True,
                        urgency=70, consequence=65, relationship=30, effort=40) -> dict:
    return {
        'thread_id': thread_id,
        'tier': tier,
        'category': category,
        'priority_score': priority_score,
        'draft_eligible': draft_eligible,
        'urgency': urgency,
        'consequence': consequence,
        'relationship': relationship,
        'effort': effort,
        'summary': 'Test summary',
        'suggested_action': 'Reply',
        'email_ids': email_ids or [],
    }


def _make_email(id='e1', account='user@gmail.com', thread_id='t1', subject='', snippet='') -> dict:
    return {
        'id': id,
        'account': account,
        'thread_id': thread_id,
        'subject': subject,
        'snippet': snippet,
        'date': 'Mon, 01 Apr 2026 08:00:00 +0000',
        'date_simple': 'Apr 1',
        'sender': 'Sender',
        'sender_email': 'sender@example.com',
        'has_attachment': False,
        'is_likely_automated': False,
        'list_unsubscribe': '',
        'message_id_header': '',
    }


def _make_thread_group(thread_id='t1', account='user@gmail.com', email_ids=None) -> dict:
    ids = email_ids or ['e1']
    return {
        'thread_id': thread_id,
        'account': account,
        'all_email_ids': ids,
        'messages': [_make_email(id=ids[0], thread_id=thread_id)],
        'total_message_count': len(ids),
    }


# ── _validate_tier_result: tier clamping ──────────────────────────────────────

def test_tier_below_1_clamped_to_1():
    result = _validate_tier_result(_make_thread_result(tier=0, category='time_sensitive_replies'))
    assert result['tier'] == 1


def test_tier_above_4_clamped_to_4():
    result = _validate_tier_result(_make_thread_result(tier=5, category='marketing_promotions'))
    assert result['tier'] == 4


def test_valid_tier_unchanged():
    for tier, cat in [(1, 'payments_due'), (2, 'job_search_recruiting'),
                      (3, 'newsletters_industry_news'), (4, 'automated_notifications')]:
        result = _validate_tier_result(_make_thread_result(tier=tier, category=cat))
        assert result['tier'] == tier


def test_negative_tier_clamped_to_1():
    result = _validate_tier_result(_make_thread_result(tier=-5, category='time_sensitive_replies'))
    assert result['tier'] == 1


# ── _validate_tier_result: priority score clamping ───────────────────────────

def test_priority_score_below_1_clamped():
    result = _validate_tier_result(_make_thread_result(tier=2, category='job_search_recruiting',
                                                       priority_score=-10))
    assert result['priority_score'] == 1


def test_priority_score_above_100_clamped():
    result = _validate_tier_result(_make_thread_result(tier=1, category='time_sensitive_replies',
                                                       priority_score=150))
    assert result['priority_score'] == 100


def test_priority_score_zero_clamped_to_1():
    result = _validate_tier_result(_make_thread_result(tier=3, category='receipts_confirmations',
                                                       priority_score=0))
    assert result['priority_score'] == 1


def test_valid_priority_score_unchanged():
    result = _validate_tier_result(_make_thread_result(tier=1, category='deadlines_due_dates',
                                                       priority_score=72))
    assert result['priority_score'] == 72


# ── _validate_tier_result: category validation ────────────────────────────────

def test_unknown_category_gets_default_for_tier():
    result = _validate_tier_result(_make_thread_result(tier=1, category='totally_fake_category'))
    assert result['category'] in VALID_CATEGORIES[1]


def test_category_inconsistent_with_tier_gets_remapped():
    # 'marketing_promotions' is Tier 4 — putting it in a Tier 1 result should remap it
    result = _validate_tier_result(_make_thread_result(tier=1, category='marketing_promotions'))
    assert result['category'] in VALID_CATEGORIES[1]


def test_valid_category_tier_pair_unchanged():
    result = _validate_tier_result(_make_thread_result(tier=2, category='professional_networking'))
    assert result['category'] == 'professional_networking'
    assert result['tier'] == 2


def test_empty_category_gets_default():
    result = _validate_tier_result(_make_thread_result(tier=3, category=''))
    assert result['category'] in VALID_CATEGORIES[3]


# ── _validate_tier_result: sub-scores clamped ────────────────────────────────

def test_sub_scores_clamped_to_0_100():
    result = _validate_tier_result(_make_thread_result(
        tier=1, category='time_sensitive_replies',
        urgency=-5, consequence=200, relationship=50, effort=50,
    ))
    assert result['urgency'] == 0
    assert result['consequence'] == 100


# ── _validate_tier_result: draft_eligible ────────────────────────────────────

def test_tier_3_never_draft_eligible():
    result = _validate_tier_result(_make_thread_result(
        tier=3, category='newsletters_industry_news', draft_eligible=True))
    assert result['draft_eligible'] is False


def test_tier_4_never_draft_eligible():
    result = _validate_tier_result(_make_thread_result(
        tier=4, category='automated_notifications', draft_eligible=True))
    assert result['draft_eligible'] is False


def test_tier_1_draft_eligible_preserved():
    result = _validate_tier_result(_make_thread_result(
        tier=1, category='time_sensitive_replies', draft_eligible=True))
    assert result['draft_eligible'] is True


# ── _rule_based_fallback ──────────────────────────────────────────────────────

def test_rule_fallback_payment_keywords_tier_1():
    email = _make_email(subject='Invoice payment due', snippet='Your invoice is past due.')
    result = _rule_based_fallback(email)
    assert result['tier'] == 1
    assert result['category'] == 'payments_due'


def test_rule_fallback_recruiter_keywords_tier_2():
    email = _make_email(subject='Interview invitation', snippet='We reviewed your application.')
    result = _rule_based_fallback(email)
    assert result['tier'] == 2
    assert result['category'] == 'job_search_recruiting'


def test_rule_fallback_receipt_keywords_tier_3():
    email = _make_email(subject='Order confirmed', snippet='Your order has been shipped.')
    result = _rule_based_fallback(email)
    assert result['tier'] == 3
    assert result['category'] == 'receipts_confirmations'


def test_rule_fallback_promo_keywords_tier_4():
    email = _make_email(subject='50% off sale today!', snippet='Big discount on all items.')
    result = _rule_based_fallback(email)
    assert result['tier'] == 4
    assert result['category'] == 'marketing_promotions'


def test_rule_fallback_default_tier_3():
    email = _make_email(subject='Random email', snippet='Nothing special here.')
    result = _rule_based_fallback(email)
    assert result['tier'] == 3


# ── validate_and_flatten ──────────────────────────────────────────────────────

def test_hallucinated_email_ids_stripped():
    real_email = _make_email(id='real_e1', thread_id='t1')
    thread_group = _make_thread_group(thread_id='t1', email_ids=['real_e1'])

    triage_result = {
        'executive_summary': 'Test',
        'thread_groups': [{
            **_make_thread_result(tier=1, category='time_sensitive_replies',
                                  thread_id='t1', email_ids=['real_e1', 'fake_id_xyz']),
        }],
    }

    scored = validate_and_flatten(triage_result, [thread_group], [real_email])
    # 'fake_id_xyz' should not appear in output
    output_ids = {e['email_id'] for e in scored}
    assert 'fake_id_xyz' not in output_ids
    assert 'real_e1' in output_ids


def test_missing_thread_id_uses_rule_based_fallback():
    email = _make_email(id='e1', thread_id='t1', subject='Invoice overdue')
    thread_group = _make_thread_group(thread_id='t1', email_ids=['e1'])
    thread_group['messages'] = [email]

    # Agent returns nothing for this thread
    triage_result = {'executive_summary': '', 'thread_groups': []}

    scored = validate_and_flatten(triage_result, [thread_group], [email])
    assert len(scored) == 1
    # Rule-based fallback for 'Invoice overdue' should produce Tier 1
    assert scored[0]['tier'] == 1


def test_output_sorted_tier_ascending_score_descending():
    emails = [_make_email(id='e1', thread_id='t1'),
              _make_email(id='e2', thread_id='t2'),
              _make_email(id='e3', thread_id='t3')]
    groups = [_make_thread_group(thread_id='t1', email_ids=['e1']),
              _make_thread_group(thread_id='t2', email_ids=['e2']),
              _make_thread_group(thread_id='t3', email_ids=['e3'])]

    triage_result = {
        'executive_summary': '',
        'thread_groups': [
            {**_make_thread_result(tier=3, category='newsletters_industry_news',
                                   priority_score=30, thread_id='t1', email_ids=['e1'])},
            {**_make_thread_result(tier=1, category='time_sensitive_replies',
                                   priority_score=90, thread_id='t2', email_ids=['e2'])},
            {**_make_thread_result(tier=2, category='professional_networking',
                                   priority_score=55, thread_id='t3', email_ids=['e3'])},
        ],
    }

    scored = validate_and_flatten(triage_result, groups, emails)
    tiers = [e['tier'] for e in scored]
    assert tiers == sorted(tiers)
