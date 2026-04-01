"""
Format scored emails into an HTML digest and Telegram summary.
v2: Stats-first layout, compact Tier 3/4 rows, draft badges, account pills,
    thread indicators, unsubscribe links, and engagement-friendly design.
"""

import logging
from collections import Counter
from datetime import datetime

from jinja2 import Template

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    'deadlines_due_dates': 'Deadline',
    'payments_due': 'Payment',
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
    'spam_unsubscribe_candidates': 'Unsub candidate',
}

TIER_CONFIG = {
    1: {'emoji': '&#128308;', 'label': 'ACTION REQUIRED TODAY', 'color': '#D64045', 'bg': '#FDF0F0'},
    2: {'emoji': '&#128992;', 'label': 'IMPORTANT \u2014 ACT THIS WEEK', 'color': '#E8913A', 'bg': '#FEF6EE'},
    3: {'emoji': '&#128994;', 'label': 'AWARENESS', 'color': '#4CAF7D', 'bg': '#F0F9F4'},
    4: {'emoji': '&#9898;', 'label': 'LOW PRIORITY', 'color': '#9E9E9E', 'bg': '#F5F5F5'},
}

# Rotating palette for inbox badge colors (assigned dynamically per account)
_PALETTE = ['#5B7FFF', '#8B5CF6', '#06B6D4', '#F59E0B', '#EF4444', '#10B981', '#F97316', '#6366F1']


def _build_account_colors(scored_emails: list[dict]) -> dict:
    """Assign a color to each unique account short-name from the palette."""
    seen = {}
    for e in scored_emails:
        short = e.get('account_short', '')
        if short and short not in seen:
            seen[short] = _PALETTE[len(seen) % len(_PALETTE)]
    return seen

HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background: #F8F9FA;">
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 16px; color: #1a1a1a; line-height: 1.5; background: #ffffff;">

  <!-- HEADER -->
  <div style="text-align: center; padding: 20px 0 16px;">
    <p style="font-size: 22px; font-weight: 700; margin: 0; color: #1a1a1a;">Morning Brief</p>
    <p style="font-size: 13px; color: #888; margin: 4px 0 0;">{{ generated_date }}</p>
  </div>

  <!-- STATS BAR -->
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom: 20px; border-radius: 10px; overflow: hidden; background: #F8F9FA;">
    <tr>
      <td style="text-align: center; padding: 12px 4px; width: 20%;">
        <p style="font-size: 11px; color: #888; margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.5px;">Total</p>
        <p style="font-size: 22px; font-weight: 700; margin: 0; color: #1a1a1a;">{{ total_count }}</p>
      </td>
      <td style="text-align: center; padding: 12px 4px; width: 20%;">
        <p style="font-size: 11px; color: {{ tier_config[1].color }}; margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.5px;">Action</p>
        <p style="font-size: 22px; font-weight: 700; margin: 0; color: {{ tier_config[1].color }};">{{ tier_counts.get(1, 0) }}</p>
      </td>
      <td style="text-align: center; padding: 12px 4px; width: 20%;">
        <p style="font-size: 11px; color: {{ tier_config[2].color }}; margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.5px;">Important</p>
        <p style="font-size: 22px; font-weight: 700; margin: 0; color: {{ tier_config[2].color }};">{{ tier_counts.get(2, 0) }}</p>
      </td>
      <td style="text-align: center; padding: 12px 4px; width: 20%;">
        <p style="font-size: 11px; color: {{ tier_config[3].color }}; margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.5px;">Aware</p>
        <p style="font-size: 22px; font-weight: 700; margin: 0; color: {{ tier_config[3].color }};">{{ tier_counts.get(3, 0) }}</p>
      </td>
      <td style="text-align: center; padding: 12px 4px; width: 20%;">
        <p style="font-size: 11px; color: {{ tier_config[4].color }}; margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.5px;">Noise</p>
        <p style="font-size: 22px; font-weight: 700; margin: 0; color: {{ tier_config[4].color }};">{{ tier_counts.get(4, 0) }}</p>
      </td>
    </tr>
  </table>

  <!-- EXECUTIVE SUMMARY -->
  <div style="background: #EEF4FF; border-radius: 10px; padding: 16px 18px; margin-bottom: 24px; border-left: 4px solid #4A7AFF;">
    <p style="font-size: 14px; line-height: 1.6; margin: 0; color: #2D3748;">{{ executive_summary }}</p>
  </div>

  <!-- DRAFT REPLY NOTICE -->
  {% if drafts_created %}
  <div style="background: #F0FFF4; border-radius: 10px; padding: 14px 18px; margin-bottom: 24px; border-left: 4px solid #38A169;">
    <p style="font-size: 13px; font-weight: 600; margin: 0 0 6px; color: #276749;">&#9998; {{ drafts_created|length }} Draft {{ 'Reply' if drafts_created|length == 1 else 'Replies' }} Created</p>
    {% for draft in drafts_created.values() %}
    <p style="font-size: 12px; margin: 3px 0; color: #4A5568;">
      <span style="display: inline-block; background: {{ account_colors.get(draft.account.split('@')[0], '#888') }}22; color: {{ account_colors.get(draft.account.split('@')[0], '#888') }}; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600;">{{ draft.account.split('@')[0] }}</span>
      &rarr; {{ draft.to }} &mdash; <em>{{ draft.subject[:50] }}</em>
    </p>
    {% endfor %}
    <p style="font-size: 11px; color: #718096; margin: 8px 0 0;">Review in your Gmail Drafts before sending.</p>
  </div>
  {% endif %}

  <!-- TIER 1 — Full cards -->
  {% set t1_emails = tier_emails.get(1, []) %}
  {% if t1_emails %}
  <p style="font-size: 15px; font-weight: 700; margin: 24px 0 10px; color: {{ tier_config[1].color }};">
    {{ tier_config[1].emoji }} {{ tier_config[1].label }} ({{ t1_emails|length }})
  </p>
  {% for email in t1_emails %}
  <div style="border: 1px solid #F5C6C6; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; background: {{ tier_config[1].bg }}; border-left: 4px solid {{ tier_config[1].color }};">
    <div style="margin-bottom: 8px;">
      <span style="display: inline-block; background: {{ account_colors.get(email.account_short, '#888') }}22; color: {{ account_colors.get(email.account_short, '#888') }}; padding: 1px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; letter-spacing: 0.3px;">{{ email.account_short }}</span>
      <span style="display: inline-block; background: {{ tier_config[1].color }}18; color: {{ tier_config[1].color }}; padding: 1px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; margin-left: 4px;">{{ category_labels.get(email.category, email.category) }}</span>
      <span style="float: right; font-size: 11px; font-weight: 600; color: {{ tier_config[1].color }};">{{ email.priority_score }}</span>
      {% if email.thread_message_count > 1 %}
      <span style="display: inline-block; background: #E2E8F0; color: #4A5568; padding: 1px 6px; border-radius: 4px; font-size: 10px; margin-left: 4px;">{{ email.thread_message_count }} msgs</span>
      {% endif %}
      {% if email.email_id in drafts_created %}
      <span style="display: inline-block; background: #C6F6D5; color: #276749; padding: 1px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; margin-left: 4px;">&#9998; DRAFT READY</span>
      {% endif %}
    </div>
    <p style="font-size: 14px; font-weight: 600; margin: 0 0 4px; color: #1a1a1a;">{{ email.sender }} &mdash; {{ email.subject[:65] }}</p>
    <p style="font-size: 13px; margin: 0 0 6px; color: #4A5568;">{{ email.summary }}</p>
    {% if email.suggested_action %}
    <div style="background: #ffffff; border-radius: 6px; padding: 8px 12px; margin-top: 6px;">
      <p style="font-size: 12px; font-weight: 600; margin: 0; color: {{ tier_config[1].color }};">&rarr; {{ email.suggested_action }}</p>
    </div>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}

  <!-- TIER 2 — Medium cards -->
  {% set t2_emails = tier_emails.get(2, []) %}
  {% if t2_emails %}
  <p style="font-size: 15px; font-weight: 700; margin: 24px 0 10px; color: {{ tier_config[2].color }};">
    {{ tier_config[2].emoji }} {{ tier_config[2].label }} ({{ t2_emails|length }})
  </p>
  {% for email in t2_emails %}
  <div style="border: 1px solid #F5DEB3; border-radius: 10px; padding: 12px 16px; margin-bottom: 8px; background: {{ tier_config[2].bg }}; border-left: 4px solid {{ tier_config[2].color }};">
    <div style="margin-bottom: 6px;">
      <span style="display: inline-block; background: {{ account_colors.get(email.account_short, '#888') }}22; color: {{ account_colors.get(email.account_short, '#888') }}; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600;">{{ email.account_short }}</span>
      <span style="display: inline-block; background: {{ tier_config[2].color }}18; color: {{ tier_config[2].color }}; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; margin-left: 3px;">{{ category_labels.get(email.category, email.category) }}</span>
      <span style="float: right; font-size: 11px; color: #888;">{{ email.priority_score }}</span>
      {% if email.thread_message_count > 1 %}
      <span style="display: inline-block; background: #E2E8F0; color: #4A5568; padding: 1px 6px; border-radius: 4px; font-size: 10px; margin-left: 3px;">{{ email.thread_message_count }} msgs</span>
      {% endif %}
    </div>
    <p style="font-size: 13px; font-weight: 600; margin: 0 0 3px; color: #1a1a1a;">{{ email.sender }} &mdash; {{ email.subject[:60] }}</p>
    <p style="font-size: 12px; margin: 0; color: #4A5568;">{{ email.summary }}</p>
    {% if email.suggested_action %}
    <p style="font-size: 11px; font-weight: 600; color: {{ tier_config[2].color }}; margin: 5px 0 0;">&rarr; {{ email.suggested_action }}</p>
    {% endif %}
  </div>
  {% endfor %}
  {% endif %}

  <!-- TIER 3 — Compact rows -->
  {% set t3_emails = tier_emails.get(3, []) %}
  {% if t3_emails %}
  <p style="font-size: 14px; font-weight: 700; margin: 24px 0 8px; color: {{ tier_config[3].color }};">
    {{ tier_config[3].emoji }} {{ tier_config[3].label }} ({{ t3_emails|length }})
  </p>
  <div style="border: 1px solid #E2E8F0; border-radius: 10px; overflow: hidden;">
  {% for email in t3_emails %}
    <div style="padding: 9px 14px; border-bottom: 1px solid #F0F0F0; {% if loop.last %}border-bottom: none;{% endif %} background: {% if loop.index is odd %}#FAFAFA{% else %}#ffffff{% endif %};">
      <span style="display: inline-block; width: 60px; font-size: 10px; color: {{ account_colors.get(email.account_short, '#888') }}; font-weight: 600;">{{ email.account_short }}</span>
      <span style="font-size: 12px; font-weight: 600; color: #2D3748;">{{ email.sender[:18] }}</span>
      <span style="font-size: 12px; color: #718096;"> &mdash; {{ email.subject[:42] }}</span>
      <span style="float: right;">
        <span style="font-size: 10px; background: #E2E8F0; color: #4A5568; padding: 1px 5px; border-radius: 3px;">{{ category_labels.get(email.category, '') }}</span>
      </span>
    </div>
  {% endfor %}
  </div>
  {% endif %}

  <!-- TIER 4 — Collapsed compact rows (muted) -->
  {% set t4_emails = tier_emails.get(4, []) %}
  {% if t4_emails %}
  <p style="font-size: 14px; font-weight: 700; margin: 24px 0 8px; color: {{ tier_config[4].color }};">
    {{ tier_config[4].emoji }} {{ tier_config[4].label }} ({{ t4_emails|length }})
  </p>
  <div style="border: 1px solid #E8E8E8; border-radius: 10px; overflow: hidden;">
  {% for email in t4_emails[:15] %}
    <div style="padding: 7px 14px; border-bottom: 1px solid #F5F5F5; {% if loop.last %}border-bottom: none;{% endif %} background: #FAFAFA;">
      <span style="font-size: 11px; color: #9E9E9E;">{{ email.sender[:20] }} &mdash; {{ email.subject[:45] }}</span>
    </div>
  {% endfor %}
  {% if t4_emails|length > 15 %}
    <div style="padding: 7px 14px; background: #F5F5F5; text-align: center;">
      <span style="font-size: 11px; color: #9E9E9E;">+ {{ t4_emails|length - 15 }} more</span>
    </div>
  {% endif %}
  </div>
  {% endif %}

  <!-- UNSUBSCRIBE CANDIDATES -->
  {% if unsub_candidates %}
  <div style="background: #FFF8F0; border-radius: 10px; padding: 14px 18px; margin-top: 24px; border: 1px solid #FEEBC8;">
    <p style="font-size: 13px; font-weight: 600; margin: 0 0 8px; color: #975A16;">&#128236; Unsubscribe Candidates</p>
    <p style="font-size: 11px; color: #975A16; margin: 0 0 8px;">These senders have appeared in Tier 4 across 3+ runs.</p>
    {% for candidate in unsub_candidates %}
    <div style="display: inline-block; margin: 2px 4px 2px 0;">
      <span style="font-size: 11px; color: #4A5568;">{{ candidate.display_name }}</span>
      <span style="font-size: 10px; color: #9E9E9E;">({{ candidate.count }}x)</span>
      {% if candidate.list_unsubscribe %}
      <a href="{{ candidate.list_unsubscribe }}" style="font-size: 10px; color: #D64045; text-decoration: none; font-weight: 600; margin-left: 2px;">[unsub]</a>
      {% endif %}
      <span style="color: #CBD5E0;">&middot;</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- FOOTER -->
  <div style="text-align: center; padding: 20px 0 8px; border-top: 1px solid #F0F0F0; margin-top: 24px;">
    <p style="font-size: 11px; color: #B0B0B0; margin: 0;">
      Morning Brief v2 &middot; {{ generated_at }} &middot; {{ model_name }}
    </p>
  </div>

</div>
</body></html>""")


def format_html_digest(
    scored_emails: list[dict],
    executive_summary: str,
    drafts_created: dict,
    unsub_candidates: list[dict],
    config: dict,
) -> str:
    """Generate the full HTML digest email."""
    # Only show thread-representative emails (one per thread)
    representative = [e for e in scored_emails if e.get('is_thread_representative')]

    tier_emails = {}
    tier_counts = {}
    for e in representative:
        t = e['tier']
        tier_emails.setdefault(t, []).append(e)
        tier_counts[t] = tier_counts.get(t, 0) + 1

    now = datetime.now()
    model_name = config.get('agent', {}).get('model', 'claude-haiku-4-5-20251001')
    account_colors = _build_account_colors(representative)

    return HTML_TEMPLATE.render(
        tier_emails=tier_emails,
        tier_config=TIER_CONFIG,
        tier_counts=tier_counts,
        category_labels=CATEGORY_LABELS,
        account_colors=ACCOUNT_COLORS,
        executive_summary=executive_summary,
        drafts_created=drafts_created,
        unsub_candidates=unsub_candidates,
        total_count=len(representative),
        generated_date=now.strftime('%A, %B %d, %Y'),
        generated_at=now.strftime('%B %d, %Y at %I:%M %p'),
        model_name=model_name,
    )


def format_telegram_summary(scored_emails: list[dict], drafts_created: dict) -> str:
    """Generate a compact Telegram message: Tier 1 action items + stats + draft count."""
    representative = [e for e in scored_emails if e.get('is_thread_representative')]
    tier1 = [e for e in representative if e['tier'] == 1]
    total = len(representative)
    tier_counts = Counter(e['tier'] for e in representative)

    lines = [f"*Morning Brief* \u2014 {datetime.now().strftime('%B %d, %Y')}\n"]

    if tier1:
        lines.append(f"\U0001F534 *{len(tier1)} action item{'s' if len(tier1) != 1 else ''}:*")
        for e in tier1:
            draft_tag = " \u270e" if e['email_id'] in drafts_created else ""
            lines.append(f"  \u2022 `[{e['priority_score']}]` {e['sender']}: {e['summary'][:55]}{draft_tag}")
    else:
        lines.append("\u2705 No urgent items today.")

    if drafts_created:
        lines.append(f"\n\u270e {len(drafts_created)} draft reply{'s' if len(drafts_created) != 1 else ''} created \u2014 review in Gmail Drafts")

    lines.append(
        f"\n\U0001F4CA {total} total | "
        f"\U0001F534 {tier_counts.get(1, 0)} | "
        f"\U0001F7E0 {tier_counts.get(2, 0)} | "
        f"\U0001F7E2 {tier_counts.get(3, 0)} | "
        f"\u26AA {tier_counts.get(4, 0)}"
    )
    lines.append("\n_Full digest in your Gmail._")

    return '\n'.join(lines)
