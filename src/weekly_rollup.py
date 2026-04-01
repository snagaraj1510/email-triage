"""
Weekly rollup digest — runs Sundays to summarize the past 7 days.
Reads from sender_history.json (no additional Gmail/LLM calls).
"""

import logging
import os
import sys
from datetime import datetime

import yaml
from jinja2 import Template

from sender_history import load_history, get_weekly_stats, get_persistent_unsubscribe_candidates
from deliver import send_gmail, send_telegram, save_local_fallback

logger = logging.getLogger(__name__)

ROLLUP_TEMPLATE = Template("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background: #F8F9FA;">
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 16px; color: #1a1a1a; line-height: 1.5; background: #ffffff;">

  <div style="text-align: center; padding: 20px 0 16px;">
    <p style="font-size: 22px; font-weight: 700; margin: 0; color: #1a1a1a;">Weekly Rollup</p>
    <p style="font-size: 13px; color: #888; margin: 4px 0 0;">{{ week_label }}</p>
  </div>

  <!-- WEEKLY STATS TABLE -->
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-radius: 10px; overflow: hidden; border: 1px solid #E2E8F0; margin-bottom: 20px;">
    <tr style="background: #F8F9FA;">
      <th style="padding: 8px 12px; font-size: 11px; text-align: left; color: #888; font-weight: 600;">Date</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #888; font-weight: 600;">Total</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #D64045; font-weight: 600;">T1</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #E8913A; font-weight: 600;">T2</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #4CAF7D; font-weight: 600;">T3</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #9E9E9E; font-weight: 600;">T4</th>
      <th style="padding: 8px 8px; font-size: 11px; text-align: center; color: #276749; font-weight: 600;">Drafts</th>
    </tr>
    {% for day in daily_stats %}
    <tr style="border-top: 1px solid #F0F0F0;">
      <td style="padding: 7px 12px; font-size: 12px; color: #4A5568;">{{ day.date }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; font-weight: 600;">{{ day.total }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; color: #D64045;">{{ day.tiers.get('1', 0) }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; color: #E8913A;">{{ day.tiers.get('2', 0) }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; color: #4CAF7D;">{{ day.tiers.get('3', 0) }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; color: #9E9E9E;">{{ day.tiers.get('4', 0) }}</td>
      <td style="padding: 7px 8px; font-size: 12px; text-align: center; color: #276749;">{{ day.drafts_created }}</td>
    </tr>
    {% endfor %}
    <!-- TOTALS ROW -->
    <tr style="border-top: 2px solid #CBD5E0; background: #F8F9FA;">
      <td style="padding: 8px 12px; font-size: 12px; font-weight: 700;">Total</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700;">{{ totals.total }}</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700; color: #D64045;">{{ totals.t1 }}</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700; color: #E8913A;">{{ totals.t2 }}</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700; color: #4CAF7D;">{{ totals.t3 }}</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700; color: #9E9E9E;">{{ totals.t4 }}</td>
      <td style="padding: 8px 8px; font-size: 12px; text-align: center; font-weight: 700; color: #276749;">{{ totals.drafts }}</td>
    </tr>
  </table>

  <!-- SUMMARY STATS -->
  <div style="background: #EEF4FF; border-radius: 10px; padding: 14px 18px; margin-bottom: 20px;">
    <p style="font-size: 13px; margin: 0; color: #2D3748;">
      <strong>{{ totals.total }}</strong> emails processed this week across {{ days_active }} day{{ 's' if days_active != 1 else '' }}.
      {% if totals.t4 > totals.total * 0.3 %}
      <br><span style="color: #975A16;">{{ totals.t4 }} ({{ ((totals.t4 / totals.total) * 100)|round|int }}%) were noise — consider unsubscribing below.</span>
      {% endif %}
    </p>
  </div>

  <!-- UNSUBSCRIBE CANDIDATES -->
  {% if unsub_candidates %}
  <div style="background: #FFF8F0; border-radius: 10px; padding: 14px 18px; margin-bottom: 20px; border: 1px solid #FEEBC8;">
    <p style="font-size: 13px; font-weight: 600; margin: 0 0 8px; color: #975A16;">&#128236; Top Unsubscribe Candidates</p>
    <table cellpadding="0" cellspacing="0" border="0" width="100%">
    {% for c in unsub_candidates %}
      <tr>
        <td style="padding: 4px 0; font-size: 12px; color: #4A5568;">{{ c.display_name }}</td>
        <td style="padding: 4px 8px; font-size: 11px; color: #9E9E9E; text-align: right;">{{ c.count }} appearances</td>
        <td style="padding: 4px 0; text-align: right;">
          {% if c.list_unsubscribe %}
          <a href="{{ c.list_unsubscribe }}" style="font-size: 10px; color: #D64045; text-decoration: none; font-weight: 600;">[unsubscribe]</a>
          {% else %}
          <span style="font-size: 10px; color: #CBD5E0;">no link</span>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </table>
  </div>
  {% endif %}

  <div style="text-align: center; padding: 16px 0 8px; border-top: 1px solid #F0F0F0;">
    <p style="font-size: 11px; color: #B0B0B0; margin: 0;">Morning Brief Weekly Rollup &middot; {{ generated_at }}</p>
  </div>

</div>
</body></html>""")


def generate_weekly_rollup(config: dict) -> tuple[str, str]:
    """
    Build the weekly rollup HTML and Telegram summary from sender_history.json.
    Returns (html, telegram_text).
    """
    history = load_history()
    daily_stats = get_weekly_stats(history)
    unsub_candidates = get_persistent_unsubscribe_candidates(history, min_appearances=3)

    if not daily_stats:
        return "<p>No data for this week.</p>", "No data for weekly rollup."

    # Compute totals
    totals = {
        'total': sum(d['total'] for d in daily_stats),
        't1': sum(int(d['tiers'].get('1', 0)) for d in daily_stats),
        't2': sum(int(d['tiers'].get('2', 0)) for d in daily_stats),
        't3': sum(int(d['tiers'].get('3', 0)) for d in daily_stats),
        't4': sum(int(d['tiers'].get('4', 0)) for d in daily_stats),
        'drafts': sum(d.get('drafts_created', 0) for d in daily_stats),
    }

    now = datetime.now()
    html = ROLLUP_TEMPLATE.render(
        daily_stats=daily_stats,
        totals=totals,
        days_active=len(daily_stats),
        unsub_candidates=unsub_candidates,
        week_label=f"Week of {daily_stats[0]['date']} to {daily_stats[-1]['date']}",
        generated_at=now.strftime('%B %d, %Y at %I:%M %p'),
    )

    # Telegram summary
    tg_lines = [
        f"*Weekly Rollup* \u2014 {now.strftime('%B %d, %Y')}\n",
        f"\U0001F4CA {totals['total']} emails | "
        f"\U0001F534 {totals['t1']} action | "
        f"\U0001F7E0 {totals['t2']} important | "
        f"\u26AA {totals['t4']} noise",
        f"\u270e {totals['drafts']} drafts created",
    ]
    if unsub_candidates:
        tg_lines.append(f"\n\U0001F4ED Top unsub candidates: {', '.join(c['display_name'] for c in unsub_candidates[:5])}")
    tg_lines.append("\n_Full rollup in your Gmail._")
    telegram = '\n'.join(tg_lines)

    return html, telegram


def main():
    """Standalone entry point for the weekly rollup (called by GitHub Actions on Sundays)."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        config = yaml.safe_load(f)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logger.info("Generating weekly rollup...")
    html, telegram = generate_weekly_rollup(config)

    if html == "<p>No data for this week.</p>":
        logger.info("No data — skipping delivery.")
        return

    # Deliver via same channels as daily digest
    status = {}
    method = config['delivery']['method']

    if method in ('gmail', 'both'):
        # Override subject for rollup
        original_template = config['delivery']['gmail'].get('subject_template', '')
        config['delivery']['gmail']['subject_template'] = 'Weekly Rollup — {date}'
        status['gmail'] = send_gmail(html, config)
        config['delivery']['gmail']['subject_template'] = original_template

    if method in ('telegram', 'both'):
        status['telegram'] = send_telegram(telegram, config)

    if not any(status.values()):
        save_local_fallback(html)

    logger.info(f"Weekly rollup delivered: {status}")


if __name__ == '__main__':
    main()
