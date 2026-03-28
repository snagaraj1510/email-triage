"""
Format classified + scored emails into an HTML digest and plain text summary.
"""

import logging
from collections import Counter
from datetime import datetime

from jinja2 import Template

logger = logging.getLogger(__name__)

# Category display names
CATEGORY_LABELS = {
    'deadlines_due_dates': 'Deadline',
    'payments_due': 'Payment due',
    'time_sensitive_replies': 'Needs reply',
    'calendar_conflicts': 'Calendar',
    'professional_networking': 'Networking',
    'financial_account_alerts': 'Financial',
    'job_search_recruiting': 'Job search',
    'property_management': 'Property',
    'newsletters_industry_news': 'Newsletter',
    'personal_correspondence': 'Personal',
    'academic_mba': 'Academic',
    'receipts_confirmations': 'Receipt',
    'marketing_promotions': 'Marketing',
    'automated_notifications': 'Notification',
    'spam_unsubscribe_candidates': 'Unsubscribe candidate',
}

TIER_CONFIG = {
    1: {'emoji': '🔴', 'label': 'ACTION REQUIRED TODAY', 'color': '#E24B4A'},
    2: {'emoji': '🟡', 'label': 'IMPORTANT — ACT THIS WEEK', 'color': '#EF9F27'},
    3: {'emoji': '🟢', 'label': 'AWARENESS', 'color': '#5DCAA5'},
    4: {'emoji': '⚪', 'label': 'LOW PRIORITY', 'color': '#B4B2A9'},
}

HTML_TEMPLATE = Template("""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 640px; margin: 0 auto; color: #333;">
  
  <div style="background: #E6F1FB; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; border-left: 4px solid #378ADD;">
    <p style="font-size: 15px; font-weight: 600; margin: 0 0 6px; color: #185FA5;">Executive Summary</p>
    <p style="font-size: 14px; line-height: 1.6; margin: 0; color: #333;">{{ executive_summary }}</p>
  </div>

  {% for tier_num in [1, 2, 3, 4] %}
  {% set tier_emails = emails_by_tier.get(tier_num, []) %}
  {% if tier_emails %}
  <h2 style="font-size: 16px; font-weight: 600; margin: 24px 0 12px; color: #333;">
    {{ tier_config[tier_num].emoji }} {{ tier_config[tier_num].label }} ({{ tier_emails|length }})
  </h2>
  
  {% for email in tier_emails %}
  <div style="border: 1px solid #e5e5e5; border-radius: 8px; padding: 14px 18px; margin-bottom: 8px; border-left: 4px solid {{ tier_config[tier_num].color }};">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
      <span style="font-size: 11px; font-weight: 600; background: {{ tier_config[tier_num].color }}20; color: {{ tier_config[tier_num].color }}; padding: 2px 8px; border-radius: 4px;">Score: {{ email.priority_score }}</span>
      <span style="font-size: 11px; color: #888;">{{ category_labels.get(email.category, email.category) }}</span>
    </div>
    <p style="font-size: 14px; font-weight: 600; margin: 0 0 3px; color: #333;">{{ email.sender }} — {{ email.subject[:70] }}</p>
    <p style="font-size: 13px; line-height: 1.5; margin: 0; color: #555;">{{ email.summary }}</p>
    {% if email.suggested_action %}
    <p style="font-size: 12px; font-weight: 600; color: {{ tier_config[tier_num].color }}; margin: 6px 0 0;">→ {{ email.suggested_action }}</p>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}
  {% endfor %}

  {% if unsubscribe_candidates %}
  <div style="background: #f8f8f6; border-radius: 8px; padding: 14px 18px; margin-top: 20px;">
    <p style="font-size: 14px; font-weight: 600; margin: 0 0 6px;">📭 Unsubscribe candidates</p>
    <p style="font-size: 13px; color: #666; margin: 0;">{{ unsubscribe_candidates | join(' · ') }}</p>
  </div>
  {% endif %}

  <div style="display: flex; gap: 10px; margin-top: 16px; flex-wrap: wrap;">
    <div style="background: #f5f5f3; border-radius: 6px; padding: 10px 14px; flex: 1; min-width: 70px; text-align: center;">
      <p style="font-size: 11px; color: #888; margin: 0 0 2px;">Total</p>
      <p style="font-size: 18px; font-weight: 600; margin: 0;">{{ total_count }}</p>
    </div>
    <div style="background: #f5f5f3; border-radius: 6px; padding: 10px 14px; flex: 1; min-width: 70px; text-align: center;">
      <p style="font-size: 11px; color: #E24B4A; margin: 0 0 2px;">Action</p>
      <p style="font-size: 18px; font-weight: 600; margin: 0;">{{ tier_counts.get(1, 0) }}</p>
    </div>
    <div style="background: #f5f5f3; border-radius: 6px; padding: 10px 14px; flex: 1; min-width: 70px; text-align: center;">
      <p style="font-size: 11px; color: #EF9F27; margin: 0 0 2px;">Important</p>
      <p style="font-size: 18px; font-weight: 600; margin: 0;">{{ tier_counts.get(2, 0) }}</p>
    </div>
    <div style="background: #f5f5f3; border-radius: 6px; padding: 10px 14px; flex: 1; min-width: 70px; text-align: center;">
      <p style="font-size: 11px; color: #888; margin: 0 0 2px;">Noise</p>
      <p style="font-size: 18px; font-weight: 600; margin: 0;">{{ tier_counts.get(4, 0) }}</p>
    </div>
  </div>

  <p style="font-size: 11px; color: #aaa; margin-top: 20px; text-align: center;">
    Morning Brief · Generated {{ generated_at }} · Powered by {{ llm_backend }}
  </p>
</div>
""")


def _generate_executive_summary(scored_emails: list[dict]) -> str:
    """Create a 2-3 sentence executive summary."""
    total = len(scored_emails)
    tier1 = [e for e in scored_emails if e['tier'] == 1]
    tier2 = [e for e in scored_emails if e['tier'] == 2]
    tier4 = [e for e in scored_emails if e['tier'] == 4]
    
    parts = [f"You have {total} emails from the last 24 hours."]
    
    if tier1:
        actions = [e['summary'][:50] for e in tier1[:3]]
        parts.append(f"{len(tier1)} require immediate action: {'; '.join(actions)}.")
    else:
        parts.append("Nothing requires immediate action today.")
    
    if tier2:
        parts.append(f"{len(tier2)} are important for this week.")
    
    if tier4 and len(tier4) > total * 0.3:
        parts.append(f"{len(tier4)} are noise — consider unsubscribing from repeat offenders.")
    
    return ' '.join(parts)


def _find_unsubscribe_candidates(scored_emails: list[dict]) -> list[str]:
    """Identify senders that consistently appear in Tier 4."""
    tier4_senders = [e['sender'] for e in scored_emails if e['tier'] == 4]
    counter = Counter(tier4_senders)
    return [sender for sender, count in counter.most_common(5) if count >= 1]


def format_html_digest(scored_emails: list[dict], config: dict) -> str:
    """Generate the full HTML digest email."""
    emails_by_tier = {}
    tier_counts = {}
    for e in scored_emails:
        t = e['tier']
        emails_by_tier.setdefault(t, []).append(e)
        tier_counts[t] = tier_counts.get(t, 0) + 1
    
    return HTML_TEMPLATE.render(
        emails_by_tier=emails_by_tier,
        tier_config=TIER_CONFIG,
        category_labels=CATEGORY_LABELS,
        executive_summary=_generate_executive_summary(scored_emails),
        unsubscribe_candidates=_find_unsubscribe_candidates(scored_emails),
        total_count=len(scored_emails),
        tier_counts=tier_counts,
        generated_at=datetime.now().strftime('%B %d, %Y at %I:%M %p'),
        llm_backend=config['llm']['backend'],
    )


def format_telegram_summary(scored_emails: list[dict]) -> str:
    """Generate a compact Telegram message (Tier 1 + stats only)."""
    tier1 = [e for e in scored_emails if e['tier'] == 1]
    total = len(scored_emails)
    tier_counts = Counter(e['tier'] for e in scored_emails)
    
    lines = [f"☀️ *Morning Brief* — {datetime.now().strftime('%B %d, %Y')}\n"]
    
    if tier1:
        lines.append(f"🔴 *{len(tier1)} action items:*")
        for e in tier1:
            lines.append(f"  • [{e['priority_score']}] {e['sender']}: {e['summary'][:60]}")
    else:
        lines.append("✅ No urgent items today.")
    
    lines.append(f"\n📊 Total: {total} | 🔴 {tier_counts.get(1, 0)} | 🟡 {tier_counts.get(2, 0)} | 🟢 {tier_counts.get(3, 0)} | ⚪ {tier_counts.get(4, 0)}")
    lines.append("\n_Full digest in your Gmail._")
    
    return '\n'.join(lines)
