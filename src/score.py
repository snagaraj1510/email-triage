"""
Apply scoring rubric and rule-based overrides to classified emails.
"""

import fnmatch
import logging
import re

logger = logging.getLogger(__name__)


def _matches_pattern(email_addr: str, patterns: list[str]) -> bool:
    """Check if an email address matches any wildcard pattern."""
    email_addr = email_addr.lower()
    for pattern in patterns:
        pattern = pattern.lower()
        if fnmatch.fnmatch(email_addr, pattern):
            return True
    return False


def _extract_dollar_amount(text: str) -> float | None:
    """Extract the largest dollar amount from text."""
    amounts = re.findall(r'\$[\d,]+(?:\.\d{2})?', text)
    if not amounts:
        amounts = re.findall(r'(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|dollars?)', text, re.IGNORECASE)
    
    if amounts:
        parsed = []
        for a in amounts:
            clean = a.replace('$', '').replace(',', '')
            try:
                parsed.append(float(clean))
            except ValueError:
                pass
        if parsed:
            return max(parsed)
    return None


def apply_scoring(
    emails: list[dict],
    classifications: list[dict],
    config: dict
) -> list[dict]:
    """
    Apply scoring formula and rule-based overrides.
    
    Merges email data with classification data and returns
    enriched results sorted by priority score.
    """
    scoring = config['scoring']
    overrides = config.get('sender_overrides', {})
    keywords_config = config.get('keywords', {})
    
    tier1_senders = overrides.get('tier1_always', [])
    tier4_senders = overrides.get('tier4_always', [])
    urgency_keywords = keywords_config.get('urgency_boost', [])
    financial_threshold = keywords_config.get('financial_threshold_usd', 100)
    
    # Build email lookup by ID
    email_lookup = {e['id']: e for e in emails}
    
    results = []
    
    for cls in classifications:
        email_id = cls.get('email_id')
        email = email_lookup.get(email_id, {})
        
        tier = cls.get('tier', 3)
        urgency = cls.get('urgency', 20)
        consequence = cls.get('consequence', 20)
        relationship = cls.get('relationship', 20)
        effort = cls.get('effort', 50)
        
        sender_email = email.get('sender_email', '')
        subject = email.get('subject', '')
        snippet = email.get('snippet', '')
        combined_text = f"{subject} {snippet}".lower()
        
        # ── Override 1: Sender-based escalation ──
        if _matches_pattern(sender_email, tier1_senders):
            tier = min(tier, 1)
            relationship = max(relationship, 85)
            logger.debug(f"Sender override → Tier 1: {sender_email}")
        
        if _matches_pattern(sender_email, tier4_senders):
            tier = max(tier, 4)
            relationship = min(relationship, 10)
            logger.debug(f"Sender override → Tier 4: {sender_email}")
        
        # ── Override 2: Keyword urgency boost ──
        for kw in urgency_keywords:
            if kw.lower() in combined_text:
                urgency = min(100, urgency + 20)
                logger.debug(f"Keyword boost +20 urgency: '{kw}' in '{subject[:40]}'")
                break
        
        # ── Override 3: Financial threshold ──
        amount = _extract_dollar_amount(combined_text)
        if amount and amount >= financial_threshold:
            tier = min(tier, 2)
            consequence = max(consequence, 60)
            logger.debug(f"Financial threshold: ${amount:.0f} in '{subject[:40]}'")
        
        # ── Recalculate score with overrides applied ──
        priority_score = round(
            urgency * scoring['urgency_weight']
            + consequence * scoring['consequence_weight']
            + relationship * scoring['relationship_weight']
            + effort * scoring['effort_weight']
        )
        priority_score = max(1, min(100, priority_score))
        
        result = {
            'email_id': email_id,
            'account': email.get('account', ''),
            'sender': email.get('sender', 'Unknown'),
            'sender_email': sender_email,
            'subject': subject,
            'date': email.get('date', ''),
            'tier': tier,
            'category': cls.get('category', 'automated_notifications'),
            'priority_score': priority_score,
            'summary': cls.get('summary', snippet[:100]),
            'suggested_action': cls.get('suggested_action'),
            'has_attachment': email.get('has_attachment', False),
        }
        results.append(result)
    
    # Sort: tier ascending, then priority score descending within tier
    results.sort(key=lambda x: (x['tier'], -x['priority_score']))
    
    logger.info(
        f"Scoring complete: "
        f"Tier1={sum(1 for r in results if r['tier'] == 1)}, "
        f"Tier2={sum(1 for r in results if r['tier'] == 2)}, "
        f"Tier3={sum(1 for r in results if r['tier'] == 3)}, "
        f"Tier4={sum(1 for r in results if r['tier'] == 4)}"
    )
    
    return results
