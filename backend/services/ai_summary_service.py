"""AI-powered news summarization via user-configured LLM provider."""
import logging

from services.api_utils import get_async_client

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "Du bist ein Finanzanalyst. Fasse die Nachrichten zu einer Aktie in 2-3 Sätzen zusammen. "
    "Beschreibe die mögliche Relevanz für den Aktienkurs (positiv, negativ oder neutral). "
    "Keine Anlageempfehlungen. Antworte auf Deutsch."
)

# Known model presets per provider
ANTHROPIC_MODELS = {
    "claude-opus-4-0-20250514": "Claude Opus 4",
    "claude-sonnet-4-20250514": "Claude Sonnet 4",
    "claude-haiku-4-5-20251001": "Claude Haiku 3.5",
}
OPENAI_MODELS = {
    "gpt-4o": "GPT-4o",
    "gpt-4o-mini": "GPT-4o mini",
    "gpt-3.5-turbo": "GPT-3.5 Turbo",
}


def _build_user_prompt(ticker: str, headlines: list[str]) -> str:
    """Build the user prompt with article headlines."""
    joined = "\n".join(f"- {h}" for h in headlines[:15])
    return f"Aktie: {ticker}\n\nAktuelle Nachrichten:\n{joined}"


async def _call_anthropic(api_key: str, model: str, prompt: str) -> str:
    """Call Anthropic Messages API."""
    client = get_async_client()
    resp = await client.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 300,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


async def _call_openai(api_key: str, model: str, prompt: str) -> str:
    """Call OpenAI Chat Completions API."""
    client = get_async_client()
    resp = await client.post(
        OPENAI_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _call_ollama(ollama_url: str, model: str, prompt: str) -> str:
    """Call local Ollama API."""
    url = (ollama_url or "http://localhost:11434").rstrip("/")
    client = get_async_client()
    resp = await client.post(
        f"{url}/api/generate",
        json={
            "model": model,
            "prompt": f"{SYSTEM_PROMPT}\n\n{prompt}",
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "")


async def summarize_ticker_news(
    headlines: list[str],
    ticker: str,
    provider: str,
    model: str,
    api_key: str | None = None,
    ollama_url: str | None = None,
) -> str:
    """Summarize news headlines for a ticker using the configured LLM.

    Returns summary text, or empty string on failure.
    """
    if not headlines:
        return ""

    prompt = _build_user_prompt(ticker, headlines)

    try:
        if provider == "anthropic":
            if not api_key:
                return ""
            return await _call_anthropic(api_key, model, prompt)
        elif provider == "openai":
            if not api_key:
                return ""
            return await _call_openai(api_key, model, prompt)
        elif provider == "ollama":
            return await _call_ollama(ollama_url, model, prompt)
        else:
            return ""
    except Exception as e:
        logger.warning("AI summary failed for %s (%s/%s): %s", ticker, provider, model, e)
        return ""


async def test_ai_provider(
    provider: str,
    model: str,
    api_key: str | None = None,
    ollama_url: str | None = None,
) -> dict:
    """Test the AI provider with a simple prompt. Returns {ok: bool, message: str}."""
    test_headlines = [
        "Apple reports record Q2 earnings, beats analyst expectations",
        "iPhone sales up 15% year-over-year",
        "Apple announces $100B share buyback program",
    ]

    try:
        result = await summarize_ticker_news(
            test_headlines, "AAPL", provider, model, api_key, ollama_url
        )
        if result:
            return {"ok": True, "message": f"Verbindung erfolgreich. Test-Zusammenfassung: {result[:200]}"}
        return {"ok": False, "message": "Keine Antwort vom Provider erhalten"}
    except Exception as e:
        return {"ok": False, "message": f"Fehler: {str(e)[:200]}"}
