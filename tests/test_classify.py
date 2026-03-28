"""
Unit tests for classification and scoring modules.
Run: python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from classify import _rule_based_classify
from score import apply_scoring, _matches_pattern, _extract_dollar_amount


# ── Test pattern matching ──

def test_wildcard_match():
    assert _matches_pattern("recruiter@anthropic.com", ["*@anthropic.com"])
    assert _matches_pattern("john@google.com", ["*@google.com"])
    assert not _matches_pattern("john@gmail.com", ["*@google.com"])

def test_noreply_match():
    assert _matches_pattern("noreply@somesite.com", ["noreply@*"])
    assert _matches_pattern("no-reply@lyftmail.com", ["no-reply@*"])


# ── Test dollar extraction ──

def test_dollar_amount_simple():
    assert _extract_dollar_amount("Payment of $150.00 due") == 150.00

def test_dollar_amount_comma():
    assert _extract_dollar_amount("Balance: $1,234.56") == 1234.56

def test_dollar_amount_none():
    assert _extract_dollar_amount("No money here") is None

def test_dollar_largest():
    assert _extract_dollar_amount("$50 fee plus $200 deposit") == 200.0


# ── Test rule-based classification ──

def test_classify_payment():
    email = {
        'id': '1', 'sender_email': 'bank@chase.com', 'sender': 'Chase',
        'subject': 'Your AutoPay payment reminder', 'snippet': 'Payment due March 30',
        'labels': [], 'has_attachment': False,
    }
    result = _rule_based_classify(email)
    assert result['category'] == 'financial_account_alerts'
    assert result['tier'] <= 2

def test_classify_job_alert():
    email = {
        'id': '2', 'sender_email': 'jobalerts-noreply@linkedin.com', 'sender': 'LinkedIn',
        'subject': 'New job: Senior Analyst at Ramp', 'snippet': '$140K salary',
        'labels': [], 'has_attachment': False,
    }
    result = _rule_based_classify(email)
    assert result['category'] == 'job_search_recruiting'

def test_classify_promo():
    email = {
        'id': '3', 'sender_email': 'offers@dominos.com', 'sender': "Domino's",
        'subject': '50% OFF pizzas!', 'snippet': 'Limited time offer',
        'labels': ['CATEGORY_PROMOTIONS'], 'has_attachment': False,
    }
    result = _rule_based_classify(email)
    assert result['tier'] == 4
    assert result['category'] == 'marketing_promotions'

def test_classify_receipt():
    email = {
        'id': '4', 'sender_email': 'no-reply@lyftmail.com', 'sender': 'Lyft',
        'subject': 'Your ride receipt', 'snippet': 'Thanks for riding',
        'labels': [], 'has_attachment': False,
    }
    result = _rule_based_classify(email)
    assert result['tier'] == 3
    assert result['category'] == 'receipts_confirmations'


# ── Test scoring overrides ──

def test_sender_override_tier1():
    emails = [{
        'id': '5', 'sender_email': 'recruiter@anthropic.com', 'sender': 'Anthropic',
        'subject': 'Interview request', 'snippet': 'We loved your profile',
        'date': 'Thu, 26 Mar 2026', 'has_attachment': False,
    }]
    classifications = [{
        'email_id': '5', 'tier': 3, 'category': 'automated_notifications',
        'urgency': 30, 'consequence': 30, 'relationship': 30, 'effort': 50,
        'priority_score': 30, 'summary': 'Interview request', 'suggested_action': None,
    }]
    config = {
        'scoring': {'urgency_weight': 0.35, 'consequence_weight': 0.30, 'relationship_weight': 0.20, 'effort_weight': 0.15},
        'sender_overrides': {'tier1_always': ['*@anthropic.com'], 'tier4_always': []},
        'keywords': {'urgency_boost': ['urgent'], 'financial_threshold_usd': 100},
    }
    
    results = apply_scoring(emails, classifications, config)
    assert results[0]['tier'] == 1  # Overridden from 3 to 1

def test_keyword_urgency_boost():
    emails = [{
        'id': '6', 'sender_email': 'prof@umich.edu', 'sender': 'Professor',
        'subject': 'URGENT: Assignment deadline extended', 'snippet': 'Please submit by Friday',
        'date': 'Thu, 26 Mar 2026', 'has_attachment': False,
    }]
    classifications = [{
        'email_id': '6', 'tier': 2, 'category': 'academic_mba',
        'urgency': 50, 'consequence': 60, 'relationship': 50, 'effort': 70,
        'priority_score': 55, 'summary': 'Assignment deadline', 'suggested_action': 'Submit by Friday',
    }]
    config = {
        'scoring': {'urgency_weight': 0.35, 'consequence_weight': 0.30, 'relationship_weight': 0.20, 'effort_weight': 0.15},
        'sender_overrides': {'tier1_always': [], 'tier4_always': []},
        'keywords': {'urgency_boost': ['urgent', 'deadline'], 'financial_threshold_usd': 100},
    }
    
    results = apply_scoring(emails, classifications, config)
    # Urgency should have been boosted from 50 to 70
    assert results[0]['priority_score'] > 55


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
