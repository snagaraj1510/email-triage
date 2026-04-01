"""
Agentic email triage using Claude Haiku.
Replaces classify.py + score.py with a single holistic reasoning call.
"""

import json
import logging
import os
import re
from datetime import datetime

import anthropic

from thread_grouper import build_agent_payload

logger = logging.getLogger(__name__)


def _load_system_prompt(config: dict) -> str:
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'prompts', 'triage_system.txt')
    with open(prompt_path, encoding='utf-8') as f:
        template = f.read()
    return template.format(personal_context=config.get('personal_context', ''))


def _clean_json(text: str) -> str:
    """Strip markdown fences and extract the outermost JSON object."""
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    # Find outermost { ... }
    start = text.find('{')
    end = text.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    return text[start:end]


def _call_haiku(system_prompt: str, user_message: str, config: dict) -> str:
    """Call Claude Haiku and return raw text response."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    agent_cfg = config.get('agent', {})
    model = agent_cfg.get('model', 'claude-haiku-4-5-20251001')
    max_tokens = agent_cfg.get('max_tokens', 8192)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        system=[{
            'type': 'text',
            'text': system_prompt,
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': user_message}],
    )
    return message.content[0].text


def _call_sonnet_fallback(system_prompt: str, user_message: str, config: dict) -> str:
    """Fallback to Sonnet when Haiku produces malformed JSON twice."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    agent_cfg = config.get('agent', {})
    model = agent_cfg.get('escalation_model', 'claude-sonnet-4-6')

    client = anthropic.Anthropic(api_key=api_key)
    logger.warning(f"Escalating to {model} for triage (Haiku parse failures)")
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=0.0,
        system=[{
            'type': 'text',
            'text': system_prompt,
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': user_message}],
    )
    return message.content[0].text


def run_triage_agent(thread_groups: list[dict], config: dict, sender_history_context: str = '') -> dict:
    """
    Run the triage agent on all thread groups in a single (or split) call.

    Returns:
        {
            'executive_summary': str,
            'thread_groups': list[dict],   # one per thread, validated downstream
        }
    """
    if not thread_groups:
        return {'executive_summary': 'No emails in the last 24 hours.', 'thread_groups': []}

    system_prompt = _load_system_prompt(config)
    if sender_history_context:
        system_prompt += f'\n\n## SENDER HISTORY\n{sender_history_context}'
    agent_cfg = config.get('agent', {})
    batch_size = agent_cfg.get('batch_size', 80)
    max_retries = agent_cfg.get('max_retries', 2)

    # Split into batches if needed (rare for typical inboxes)
    all_results = []
    executive_summaries = []

    payload = build_agent_payload(thread_groups)
    batches = [payload[i:i + batch_size] for i in range(0, len(payload), batch_size)]

    today_str = datetime.now().strftime('%A, %B %d, %Y, %I:%M %p %Z')

    for batch_idx, batch in enumerate(batches):
        n = len(batch)
        user_message = (
            f"Current date/time: {today_str}\n\n"
            f"Classify all {n} thread group(s) below. "
            f"Return a JSON object with 'executive_summary' and 'thread_groups' array "
            f"containing exactly {n} entries.\n\n"
            f"{json.dumps(batch, indent=2)}"
        )

        parsed = None
        raw_response = None

        for attempt in range(max_retries):
            try:
                if attempt < max_retries - 1:
                    raw_response = _call_haiku(system_prompt, user_message, config)
                else:
                    # Final attempt: escalate to Sonnet
                    raw_response = _call_sonnet_fallback(system_prompt, user_message, config)

                cleaned = _clean_json(raw_response)
                parsed = json.loads(cleaned)

                # Validate structure
                if 'thread_groups' not in parsed:
                    raise ValueError("Response missing 'thread_groups' key")

                logger.info(
                    f"Batch {batch_idx + 1}/{len(batches)}: "
                    f"classified {len(parsed['thread_groups'])} thread groups "
                    f"(attempt {attempt + 1})"
                )
                break

            except Exception as e:
                logger.warning(f"Triage attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    # Re-prompt with explicit JSON correction instruction
                    user_message = (
                        "Your previous response was not valid JSON or was missing required fields.\n"
                        "Return ONLY a valid JSON object — no markdown, no commentary.\n\n"
                        + user_message
                    )

        if parsed is None:
            logger.error(f"All triage attempts failed for batch {batch_idx + 1}. "
                         "Guardrails will apply rule-based fallback.")
            parsed = {'executive_summary': '', 'thread_groups': []}

        all_results.extend(parsed.get('thread_groups', []))
        if parsed.get('executive_summary'):
            executive_summaries.append(parsed['executive_summary'])

    return {
        'executive_summary': ' '.join(executive_summaries) or 'No summary available.',
        'thread_groups': all_results,
    }
