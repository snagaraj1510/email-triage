"""
Validate triage agent output and flatten thread groups into a scored email list.
Falls back to rule-based classification for missing or unparseable results.
"""

import logging

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {
    1: {'deadlines_due_dates', 'payments_due', 'time_sensitive_replies', 'calendar_conflicts'},
    2: {'professional_networking', 'financial_account_alerts', 'job_search_recruiting', 'property_management'},
    3: {'newsletters_industry_news', 'personal_correspondence', 'academic_mba', 'receipts_confirmations'},
    4: {'marketing_promotions', 'automated_notifications', 'spam_unsubscribe_candidates'},
}
ALL_CATEGORIES = {cat for cats in VALID_CATEGORIES.values() for cat in cats}
DEFAULT_CATEGORY = {1: 'time_sensitive_replies', 2: 'financial_account_alerts',
                    3: 'automated_notifications', 4: 'automated_notifications'}


def _rule_based_fallback(email: dict) -> dict:
    """Minimal rule-based classifier used only when the agent completely fails."""
    combined = f"{email.get('subject', '')} {email.get('snippet', '')}".lower()

    if any(k in combined for k in ['payment due', 'invoice', 'past due', 'final notice', 'overdue']):
        return {'tier': 1, 'category': 'payments_due', 'priority_score': 60,
                'summary': f"Payment-related email from {email.get('sender', 'unknown')}",
                'suggested_action': 'Review and action payment.', 'draft_eligible': False,
                'urgency': 70, 'consequence': 65, 'relationship': 25, 'effort': 80}

    if any(k in combined for k in ['interview', 'offer', 'application update', 'recruiter']):
        return {'tier': 2, 'category': 'job_search_recruiting', 'priority_score': 55,
                'summary': f"Recruiting email from {email.get('sender', 'unknown')}",
                'suggested_action': 'Review and respond if relevant.', 'draft_eligible': False,
                'urgency': 35, 'consequence': 50, 'relationship': 30, 'effort': 75}

    if any(k in combined for k in ['receipt', 'order confirmed', 'shipped', 'delivered']):
        return {'tier': 3, 'category': 'receipts_confirmations', 'priority_score': 18,
                'summary': f"Receipt or confirmation from {email.get('sender', 'unknown')}",
                'suggested_action': None, 'draft_eligible': False,
                'urgency': 5, 'consequence': 10, 'relationship': 10, 'effort': 95}

    if any(k in combined for k in ['sale', 'off', 'discount', 'promo', 'deal']):
        return {'tier': 4, 'category': 'marketing_promotions', 'priority_score': 8,
                'summary': f"Promotional email from {email.get('sender', 'unknown')}",
                'suggested_action': None, 'draft_eligible': False,
                'urgency': 2, 'consequence': 3, 'relationship': 5, 'effort': 95}

    return {'tier': 3, 'category': 'automated_notifications', 'priority_score': 20,
            'summary': f"Notification from {email.get('sender', 'unknown')}",
            'suggested_action': None, 'draft_eligible': False,
            'urgency': 10, 'consequence': 10, 'relationship': 15, 'effort': 85}


def _validate_tier_result(result: dict) -> dict:
    """Clamp and repair a single thread group result from the agent."""
    # G2: Tier range
    tier = result.get('tier', 3)
    if not isinstance(tier, int) or tier < 1:
        tier = 1
    elif tier > 4:
        tier = 4
    result['tier'] = tier

    # G3+G4: Category validity and tier-category consistency
    category = result.get('category', '')
    if category not in ALL_CATEGORIES:
        logger.warning(f"Unknown category '{category}' — defaulting for tier {tier}")
        category = DEFAULT_CATEGORY[tier]
    elif category not in VALID_CATEGORIES[tier]:
        logger.warning(f"Category '{category}' inconsistent with tier {tier} — remapping")
        category = DEFAULT_CATEGORY[tier]
    result['category'] = category

    # G6: Priority score range
    score = result.get('priority_score', 25)
    result['priority_score'] = max(1, min(100, int(score)))

    # Ensure score sub-components exist and are in range
    for field in ('urgency', 'consequence', 'relationship', 'effort'):
        result[field] = max(0, min(100, int(result.get(field, 20))))

    # Ensure draft_eligible is a bool
    result['draft_eligible'] = bool(result.get('draft_eligible', False))

    # Tier 3-4 should never be draft eligible
    if tier >= 3:
        result['draft_eligible'] = False

    return result


def validate_and_flatten(
    triage_result: dict,
    thread_groups: list[dict],
    all_emails: list[dict],
) -> list[dict]:
    """
    Validate triage agent output and return a flat list of scored email dicts,
    one per individual email (expanding thread groups back to per-message records).

    G1: Any missing thread_ids are classified via rule-based fallback.
    G5: Any hallucinated email_ids are stripped.
    """
    valid_email_ids = {e['id'] for e in all_emails}
    email_lookup = {e['id']: e for e in all_emails}
    thread_group_lookup = {g['thread_id']: g for g in thread_groups}

    # Build a map of thread_id → agent result
    agent_results = {}
    for item in triage_result.get('thread_groups', []):
        tid = item.get('thread_id', '')
        if not tid:
            continue
        # G5: strip hallucinated email IDs
        item['email_ids'] = [eid for eid in item.get('email_ids', []) if eid in valid_email_ids]
        agent_results[tid] = _validate_tier_result(item)

    # G1: identify missing thread_ids
    expected_thread_ids = {g['thread_id'] for g in thread_groups}
    missing = expected_thread_ids - set(agent_results.keys())
    if missing:
        logger.warning(f"Agent dropped {len(missing)} thread(s) — applying rule-based fallback")

    scored_emails = []

    for group in thread_groups:
        tid = group['thread_id']

        if tid in agent_results:
            result = agent_results[tid]
        else:
            # Fallback: classify using the most recent message in the thread
            latest_email = group['messages'][0]
            fb = _rule_based_fallback(latest_email)
            result = {
                'thread_id': tid,
                'email_ids': group['all_email_ids'],
                **fb,
                'summary': fb['summary'] + ' [fallback]',
            }
            result = _validate_tier_result(result)

        # Expand thread group back to individual email records
        for email_id in group['all_email_ids']:
            email = email_lookup.get(email_id, {})
            scored_emails.append({
                'email_id': email_id,
                'thread_id': tid,
                'account': email.get('account', group['account']),
                'account_short': email.get('account', '').split('@')[0],
                'sender': email.get('sender', 'Unknown'),
                'sender_email': email.get('sender_email', ''),
                'subject': email.get('subject', ''),
                'date': email.get('date', ''),
                'date_simple': email.get('date_simple', ''),
                'tier': result['tier'],
                'category': result['category'],
                'priority_score': result['priority_score'],
                'urgency': result['urgency'],
                'consequence': result['consequence'],
                'relationship': result['relationship'],
                'effort': result['effort'],
                'summary': result.get('summary', ''),
                'suggested_action': result.get('suggested_action'),
                'draft_eligible': result.get('draft_eligible', False),
                'has_attachment': email.get('has_attachment', False),
                'is_likely_automated': email.get('is_likely_automated', False),
                'list_unsubscribe': email.get('list_unsubscribe', ''),
                'message_id_header': email.get('message_id_header', ''),
                'thread_message_count': group['total_message_count'],
                'is_thread_representative': (email_id == group['all_email_ids'][0]),
            })

    # Sort: tier ascending, then priority score descending
    scored_emails.sort(key=lambda x: (x['tier'], -x['priority_score']))

    tier_counts = {t: sum(1 for e in scored_emails if e['tier'] == t and e['is_thread_representative'])
                   for t in (1, 2, 3, 4)}
    logger.info(
        f"Validated: T1={tier_counts[1]} T2={tier_counts[2]} "
        f"T3={tier_counts[3]} T4={tier_counts[4]} "
        f"({len(scored_emails)} total email records)"
    )
    return scored_emails
