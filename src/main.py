#!/usr/bin/env python3
"""
Morning Brief v2 — Agentic Email Triage

Pipeline: fetch → thread-group → triage agent → guardrails → drafts → format → deliver

Usage:
    python src/main.py                  # Full run with delivery
    python src/main.py --dry-run        # Triage without delivery or drafts
    python src/main.py --save-local     # Save HTML locally instead of emailing
    python src/main.py --no-drafts      # Skip draft creation
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_emails import fetch_emails
from thread_grouper import group_threads
from triage_agent import run_triage_agent
from guardrails import validate_and_flatten
from draft_agent import create_drafts
from sender_history import load_history, update_history, save_history, get_persistent_unsubscribe_candidates, get_tier4_senders_for_prompt
from format_digest import format_html_digest, format_telegram_summary
from deliver import deliver, save_local_fallback


def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    log_config = config.get('logging', {})
    log_file = os.path.join(
        os.path.dirname(__file__), '..',
        log_config.get('file', 'logs/morning-brief.log'),
    )
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, log_config.get('level', 'INFO')),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description='Morning Brief v2 — Agentic Email Triage')
    parser.add_argument('--dry-run', action='store_true', help='Triage without delivering or creating drafts')
    parser.add_argument('--save-local', action='store_true', help='Save HTML locally instead of emailing')
    parser.add_argument('--no-drafts', action='store_true', help='Skip draft reply creation')
    args = parser.parse_args()

    config = load_config()
    setup_logging(config)
    logger = logging.getLogger('morning-brief')

    start = time.time()
    logger.info('=' * 60)
    logger.info(f"Morning Brief v2 — {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}")
    logger.info('=' * 60)

    # ── Step 1: Fetch ──
    logger.info('Step 1/6: Fetching emails...')
    try:
        emails = fetch_emails(config)
        logger.info(f'Fetched {len(emails)} emails')
    except Exception as e:
        logger.error(f'Fetch failed: {e}')
        sys.exit(1)

    if not emails:
        logger.info('No new emails. Exiting.')
        sys.exit(0)

    # ── Step 2: Thread grouping ──
    logger.info('Step 2/6: Grouping into threads...')
    thread_groups = group_threads(emails)

    # ── Step 3: Agentic triage ──
    logger.info('Step 3/6: Running triage agent...')
    try:
        _pre_triage_history = load_history()
        sender_history_context = get_tier4_senders_for_prompt(_pre_triage_history)
        triage_result = run_triage_agent(thread_groups, config, sender_history_context)
        logger.info(f"Agent returned {len(triage_result.get('thread_groups', []))} thread classifications")
    except Exception as e:
        logger.error(f'Triage agent failed: {e}')
        sys.exit(1)

    # ── Step 4: Guardrails ──
    logger.info('Step 4/6: Validating output...')
    scored_emails = validate_and_flatten(triage_result, thread_groups, emails)

    # Quick summary for log / dry-run
    representative = [e for e in scored_emails if e.get('is_thread_representative')]
    tier_summary = {t: sum(1 for e in representative if e['tier'] == t) for t in (1, 2, 3, 4)}
    logger.info(f"Results: T1={tier_summary[1]} | T2={tier_summary[2]} | T3={tier_summary[3]} | T4={tier_summary[4]}")

    if args.dry_run:
        logger.info('Dry run — printing results:')
        for e in representative:
            label = {1: '[T1]', 2: '[T2]', 3: '[T3]', 4: '[T4]'}[e['tier']]
            draft = ' *DRAFT' if e.get('draft_eligible') else ''
            print(f"  {label} [{e['priority_score']:3d}] {e['account_short']:15s} | {e['sender'][:20]:20s} | {e['subject'][:50]}{draft}")
        logger.info(f"Completed in {time.time() - start:.1f}s (dry run)")
        return

    # ── Step 5: Create drafts ──
    drafts_created = {}
    if not args.no_drafts:
        logger.info('Step 5/6: Creating draft replies...')
        try:
            drafts_created = create_drafts(scored_emails, config)
        except Exception as e:
            logger.error(f'Draft creation failed: {e}')
    else:
        logger.info('Step 5/6: Skipped (--no-drafts)')

    # ── Step 5b: Update sender history ──
    try:
        history = load_history()
        history = update_history(history, scored_emails, drafts_created)
        save_history(history)
    except Exception as e:
        logger.warning(f'Sender history update failed (non-fatal): {e}')

    # ── Step 6: Format & Deliver ──
    logger.info('Step 6/6: Formatting and delivering...')
    unsub_candidates = []
    try:
        history = load_history()
        unsub_candidates = get_persistent_unsubscribe_candidates(history)
    except Exception:
        pass

    executive_summary = triage_result.get('executive_summary', '')
    html_digest = format_html_digest(scored_emails, executive_summary, drafts_created, unsub_candidates, config)
    telegram_summary = format_telegram_summary(scored_emails, drafts_created)

    if args.save_local:
        path = save_local_fallback(html_digest)
        logger.info(f'Saved locally: {path}')
    else:
        status = deliver(html_digest, telegram_summary, config)
        for channel, result in status.items():
            if isinstance(result, bool):
                logger.info(f"Delivery [{channel}]: {'success' if result else 'failed'}")
            else:
                logger.info(f"Delivery [{channel}]: {result}")

    elapsed = time.time() - start
    logger.info(f'Morning Brief v2 completed in {elapsed:.1f}s')
    logger.info('=' * 60)


if __name__ == '__main__':
    main()
