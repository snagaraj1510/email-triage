"""
Classify emails using an LLM (Ollama or Anthropic API).
Falls back to rule-based classification if LLM fails.
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

# Max emails per LLM call to stay within context limits
BATCH_SIZE = 25


def _load_prompt(config: dict) -> str:
    """Load the classification prompt template."""
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'classify_prompt.txt')
    with open(prompt_path) as f:
        return f.read()


def _prepare_email_batch(emails: list[dict]) -> str:
    """Convert emails to compact JSON for the prompt."""
    compact = []
    for e in emails:
        compact.append({
            'id': e['id'],
            'from': f"{e['sender']} <{e['sender_email']}>",
            'subject': e['subject'],
            'date': e['date'],
            'preview': e['snippet'][:200],
        })
    return json.dumps(compact, indent=2)


def _call_ollama(prompt: str, config: dict) -> str:
    """Call local Ollama API."""
    ollama_config = config['llm']['ollama']
    url = f"{ollama_config['base_url']}/api/generate"
    
    response = requests.post(url, json={
        'model': ollama_config['model'],
        'prompt': prompt,
        'stream': False,
        'options': {
            'temperature': 0.1,
            'num_predict': 4096,
        }
    }, timeout=120)
    response.raise_for_status()
    return response.json()['response']


def _call_anthropic(prompt: str, config: dict) -> str:
    """Call Anthropic API."""
    import anthropic
    
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    client = anthropic.Anthropic(api_key=api_key)
    anthropic_config = config['llm']['anthropic']
    
    message = client.messages.create(
        model=anthropic_config['model'],
        max_tokens=anthropic_config.get('max_tokens', 4096),
        temperature=0.1,
        messages=[{
            'role': 'user',
            'content': prompt
        }]
    )
    return message.content[0].text


def _parse_llm_response(response_text: str) -> list[dict]:
    """Parse JSON from LLM response, handling common formatting issues."""
    # Strip markdown code fences if present
    cleaned = re.sub(r'```json\s*', '', response_text)
    cleaned = re.sub(r'```\s*', '', cleaned)
    cleaned = cleaned.strip()
    
    # Find the JSON array
    start = cleaned.find('[')
    end = cleaned.rfind(']') + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON array found in response")
    
    return json.loads(cleaned[start:end])


def _rule_based_classify(email: dict) -> dict:
    """Fallback rule-based classification when LLM is unavailable."""
    sender = email['sender_email']
    subject = email['subject'].lower()
    snippet = email['snippet'].lower()
    combined = f"{subject} {snippet}"
    
    # Check for financial/payment keywords
    payment_keywords = ['payment', 'autopay', 'bill', 'invoice', 'due', 'statement', 'balance']
    if any(kw in combined for kw in payment_keywords):
        return {
            'email_id': email['id'],
            'tier': 2,
            'category': 'financial_account_alerts',
            'priority_score': 55,
            'summary': f"Financial notification from {email['sender']}",
            'suggested_action': 'Review payment details',
            'urgency': 50, 'consequence': 60, 'relationship': 30, 'effort': 80,
        }
    
    # Check for job-related
    job_keywords = ['job', 'role', 'position', 'interview', 'application', 'hiring', 'recruiter', 'salary']
    if any(kw in combined for kw in job_keywords) or 'jobalerts' in sender:
        return {
            'email_id': email['id'],
            'tier': 2,
            'category': 'job_search_recruiting',
            'priority_score': 50,
            'summary': f"Job alert: {email['subject'][:60]}",
            'suggested_action': 'Review if role matches your criteria',
            'urgency': 30, 'consequence': 40, 'relationship': 20, 'effort': 70,
        }
    
    # Check for marketing/promos
    promo_keywords = ['offer', 'discount', 'sale', '%off', 'promo', 'deal', 'limited time', 'shop now']
    if any(kw in combined for kw in promo_keywords) or 'CATEGORY_PROMOTIONS' in email.get('labels', []):
        return {
            'email_id': email['id'],
            'tier': 4,
            'category': 'marketing_promotions',
            'priority_score': 8,
            'summary': f"Promotion from {email['sender']}",
            'suggested_action': None,
            'urgency': 5, 'consequence': 5, 'relationship': 5, 'effort': 90,
        }
    
    # Check for receipts
    receipt_keywords = ['receipt', 'order confirmed', 'shipping', 'delivered', 'your ride', 'your order']
    if any(kw in combined for kw in receipt_keywords):
        return {
            'email_id': email['id'],
            'tier': 3,
            'category': 'receipts_confirmations',
            'priority_score': 20,
            'summary': f"Receipt/confirmation from {email['sender']}",
            'suggested_action': None,
            'urgency': 10, 'consequence': 10, 'relationship': 15, 'effort': 95,
        }
    
    # Default: Tier 3 awareness
    return {
        'email_id': email['id'],
        'tier': 3,
        'category': 'automated_notifications',
        'priority_score': 25,
        'summary': f"Notification from {email['sender']}",
        'suggested_action': None,
        'urgency': 15, 'consequence': 15, 'relationship': 20, 'effort': 80,
    }


def classify_emails(emails: list[dict], config: dict) -> list[dict]:
    """
    Classify emails using configured LLM backend.
    Falls back to rule-based classification on failure.
    
    Returns list of classification dicts with email_id, tier, category, 
    priority_score, summary, suggested_action.
    """
    if not emails:
        return []
    
    prompt_template = _load_prompt(config)
    backend = config['llm']['backend']
    all_classifications = []
    
    # Process in batches
    for i in range(0, len(emails), BATCH_SIZE):
        batch = emails[i:i + BATCH_SIZE]
        emails_json = _prepare_email_batch(batch)
        
        prompt = prompt_template.format(
            personal_context=config.get('personal_context', ''),
            emails_json=emails_json,
        )
        
        retries = 3
        for attempt in range(retries):
            try:
                logger.info(f"Classifying batch {i // BATCH_SIZE + 1} ({len(batch)} emails) via {backend}")
                
                if backend == 'ollama':
                    response = _call_ollama(prompt, config)
                elif backend == 'anthropic':
                    response = _call_anthropic(prompt, config)
                else:
                    raise ValueError(f"Unknown LLM backend: {backend}")
                
                classifications = _parse_llm_response(response)
                all_classifications.extend(classifications)
                logger.info(f"Successfully classified {len(classifications)} emails")
                break
                
            except Exception as e:
                logger.warning(f"LLM classification attempt {attempt + 1} failed: {e}")
                if attempt == retries - 1:
                    logger.error("All LLM attempts failed, falling back to rule-based classification")
                    for email in batch:
                        all_classifications.append(_rule_based_classify(email))
    
    return all_classifications
