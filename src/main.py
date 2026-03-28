#!/usr/bin/env python3
"""
Morning Brief — Main Orchestrator
Fetches, classifies, scores, formats, and delivers your daily email digest.

Usage:
    python src/main.py                  # Full run with delivery
    python src/main.py --dry-run        # Classify and score, but don't deliver
    python src/main.py --save-local     # Save HTML locally instead of emailing
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

import yaml

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_emails import fetch_emails
from classify import classify_emails
from score import apply_scoring
from format_digest import format_html_digest, format_telegram_summary
from deliver import deliver, save_local_fallback


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def setup_logging(config: dict):
    """Configure logging."""
    log_config = config.get('logging', {})
    log_file = os.path.join(
        os.path.dirname(__file__), '..', 
        log_config.get('file', 'logs/morning-brief.log')
    )
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_config.get('level', 'INFO')),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description='Morning Brief — Email Triage')
    parser.add_argument('--dry-run', action='store_true', help='Classify without delivering')
    parser.add_argument('--save-local', action='store_true', help='Save HTML locally')
    args = parser.parse_args()
    
    config = load_config()
    setup_logging(config)
    logger = logging.getLogger('morning-brief')
    
    start_time = time.time()
    logger.info("=" * 60)
    logger.info(f"Morning Brief — {datetime.now().strftime('%A, %B %d, %Y %I:%M %p')}")
    logger.info("=" * 60)
    
    # ── Step 1: Fetch ──
    logger.info("Step 1/4: Fetching emails...")
    try:
        emails = fetch_emails(config)
        logger.info(f"Fetched {len(emails)} emails")
    except Exception as e:
        logger.error(f"Failed to fetch emails: {e}")
        sys.exit(1)
    
    if not emails:
        logger.info("No new emails found. Exiting.")
        sys.exit(0)
    
    # ── Step 2: Classify ──
    logger.info("Step 2/4: Classifying emails...")
    try:
        classifications = classify_emails(emails, config)
        logger.info(f"Classified {len(classifications)} emails")
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        sys.exit(1)
    
    # ── Step 3: Score ──
    logger.info("Step 3/4: Applying scoring rubric...")
    scored_emails = apply_scoring(emails, classifications, config)
    
    tier_summary = {
        1: sum(1 for e in scored_emails if e['tier'] == 1),
        2: sum(1 for e in scored_emails if e['tier'] == 2),
        3: sum(1 for e in scored_emails if e['tier'] == 3),
        4: sum(1 for e in scored_emails if e['tier'] == 4),
    }
    logger.info(f"Results: T1={tier_summary[1]} | T2={tier_summary[2]} | T3={tier_summary[3]} | T4={tier_summary[4]}")

    if args.dry_run:
        logger.info("Dry run -- printing results:")
        for e in scored_emails:
            tier_label = {1: '[T1]', 2: '[T2]', 3: '[T3]', 4: '[T4]'}[e['tier']]
            print(f"  {tier_label} [{e['priority_score']:3d}] {e.get('account','')[:15]:15s} | {e['sender'][:20]:20s} | {e['subject'][:50]}")
        elapsed = time.time() - start_time
        logger.info(f"Completed in {elapsed:.1f}s (dry run)")
        return
    
    # ── Step 4: Format & Deliver ──
    logger.info("Step 4/4: Formatting and delivering...")
    html_digest = format_html_digest(scored_emails, config)
    telegram_summary = format_telegram_summary(scored_emails)
    
    if args.save_local:
        path = save_local_fallback(html_digest)
        logger.info(f"Saved locally: {path}")
    else:
        status = deliver(html_digest, telegram_summary, config)
        for channel, result in status.items():
            logger.info(f"Delivery [{channel}]: {'✅ Success' if result else '❌ Failed'}")
    
    elapsed = time.time() - start_time
    logger.info(f"Morning Brief completed in {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
