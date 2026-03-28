"""
Deliver the formatted digest via Gmail (self-email) and/or Telegram.
"""

import base64
import logging
import os
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)


def _get_gmail_service(config: dict):
    """Build authenticated Gmail API service for sending."""
    token_path = os.path.join(os.path.dirname(__file__), '..', config['gmail']['accounts'][0]['token_path'])
    scopes = config['gmail']['scopes']
    
    creds = Credentials.from_authorized_user_file(token_path, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
    
    return build('gmail', 'v1', credentials=creds)


def send_gmail(html_content: str, config: dict) -> bool:
    """Send the digest as an HTML email to yourself via Gmail API."""
    try:
        service = _get_gmail_service(config)
        delivery = config['delivery']['gmail']
        
        today = datetime.now().strftime('%A, %B %d, %Y')
        subject = delivery['subject_template'].format(date=today)
        
        message = MIMEMultipart('alternative')
        message['to'] = delivery['send_to']
        message['subject'] = subject
        
        # Plain text fallback
        plain_text = "Your Morning Brief is ready. View in HTML for best experience."
        message.attach(MIMEText(plain_text, 'plain'))
        message.attach(MIMEText(html_content, 'html'))
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        
        logger.info(f"Digest sent to {delivery['send_to']}")
        return True
        
    except Exception as e:
        logger.error(f"Gmail delivery failed: {e}")
        return False


def send_telegram(text_content: str, config: dict) -> bool:
    """Send a compact summary via Telegram bot."""
    try:
        tg = config['delivery']['telegram']
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN') or tg.get('bot_token', '')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID') or tg.get('chat_id', '')
        
        if not bot_token or not chat_id:
            logger.warning("Telegram not configured (missing bot_token or chat_id)")
            return False
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': text_content,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True,
        }, timeout=30)
        
        response.raise_for_status()
        logger.info(f"Telegram message sent to chat_id={chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"Telegram delivery failed: {e}")
        return False


def save_local_fallback(html_content: str) -> str:
    """Save digest as local HTML file when delivery fails."""
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    os.makedirs(output_dir, exist_ok=True)
    
    filename = f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w') as f:
        f.write(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Morning Brief</title>
<style>body {{ max-width: 680px; margin: 40px auto; padding: 0 20px; }}</style>
</head><body>{html_content}</body></html>""")
    
    logger.info(f"Digest saved locally: {filepath}")
    return filepath


def deliver(html_content: str, telegram_content: str, config: dict) -> dict:
    """
    Deliver the digest via configured method(s).
    Returns dict with delivery status for each channel.
    """
    method = config['delivery']['method']
    status = {}
    
    if method in ('gmail', 'both'):
        status['gmail'] = send_gmail(html_content, config)
    
    if method in ('telegram', 'both'):
        status['telegram'] = send_telegram(telegram_content, config)
    
    # If all deliveries failed, save locally
    if not any(status.values()):
        fallback_path = save_local_fallback(html_content)
        status['local_fallback'] = fallback_path
        logger.warning(f"All delivery methods failed. Saved locally: {fallback_path}")
    
    return status
