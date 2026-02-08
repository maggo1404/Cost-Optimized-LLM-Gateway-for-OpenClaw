"""
Anthropic Provider - Claude mit Prompt Caching
=============================================

Verwendet Anthropic Claude für Premium-Tier.
Aktiviert Prompt Caching für 90% Rabatt auf System-Prompts.
"""

import logging
from typing import Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# Static system prompt for caching
STATIC_SYSTEM_PROMPT = """Du bist ein hilfreicher AI Coding Assistant.

## Fähigkeiten
- Code-Erklärungen und Dokumentation
- Bug-Fixes und Debugging-Hilfe
- Refactoring-Vorschläge
- Shell-Kommando-Generierung
- Code-Reviews und Best Practices

## Verhalten
- Antworte präzise und technisch korrekt
- Verwende Code-Blöcke mit korrekter Syntax-Hervorhebung
- Erkläre komplexe Konzepte verständlich
- Gib Sicherheitshinweise bei kritischen Operationen
- Frage nach bei unklaren Anforderungen

## Ausgabeformat
- Strukturiere Antworten klar mit Überschriften
- Verwende Markdown für Formatierung
- Zeige Code-Beispiele wo hilfreich
- Halte Erklärungen fokussiert und relevant"""


class AnthropicProvider:
    """
    Anthropic Claude provider with prompt caching.
    
    Features:
    - Claude Sonnet for premium tier
    - Prompt caching for 90% system prompt cost reduction
    - Streaming support
    - Usage tracking
    """
    
    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
        timeout: float = 60.0
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.max_tokens = max_tokens
        
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "prompt-caching-2024-07-31",
                "Content-Type": "application/json"
            },
            timeout=timeout
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10)
    )
    async def generate(
        self,
        messages: list,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7,
        use_cache: bool = True,
        system_prompt: str = None
    ) -> dict:
        """
        Generate response using Claude.
        
        Args:
            messages: Conversation messages
            model: Model to use (default: claude-sonnet-4-20250514)
            max_tokens: Max output tokens
            temperature: Sampling temperature
            use_cache: Enable prompt caching for system prompt
            system_prompt: Custom system prompt (default: STATIC_SYSTEM_PROMPT)
            
        Returns:
            dict with content, usage, model
        """
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        system = system_prompt or STATIC_SYSTEM_PROMPT
        
        # Format messages
        formatted_messages = self._format_messages(messages)
        
        # Build request body
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": formatted_messages
        }
        
        # Add system prompt with caching
        if use_cache:
            body["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"}
            }]
        else:
            body["system"] = system
        
        # Make request
        response = await self._client.post(
            "/v1/messages",
            json=body
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Extract content
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
        
        # Extract usage with cache info
        usage = data.get("usage", {})
        usage_info = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0)
        }
        
        # Log cache effectiveness
        if use_cache:
            cache_read = usage_info["cache_read_input_tokens"]
            cache_write = usage_info["cache_creation_input_tokens"]
            logger.info(f"Anthropic cache: read={cache_read}, write={cache_write}")
        
        return {
            "content": content,
            "usage": usage_info,
            "model": model,
            "stop_reason": data.get("stop_reason")
        }
    
    async def generate_stream(
        self,
        messages: list,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7,
        use_cache: bool = True
    ):
        """
        Generate streaming response.
        
        Yields content chunks as they arrive.
        """
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        formatted_messages = self._format_messages(messages)
        
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": formatted_messages,
            "stream": True
        }
        
        if use_cache:
            body["system"] = [{
                "type": "text",
                "text": STATIC_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }]
        
        async with self._client.stream(
            "POST",
            "/v1/messages",
            json=body
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    
                    try:
                        import json
                        event = json.loads(data)
                        
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                                
                    except json.JSONDecodeError:
                        continue
    
    def _format_messages(self, messages: list) -> list:
        """Format messages for Anthropic API."""
        formatted = []
        
        for msg in messages:
            # Handle different message formats
            if hasattr(msg, "model_dump"):
                msg_dict = msg.model_dump()
            elif hasattr(msg, "dict"):
                msg_dict = msg.dict()
            elif isinstance(msg, dict):
                msg_dict = msg
            else:
                msg_dict = {"role": str(msg.role), "content": str(msg.content)}
            
            role = msg_dict.get("role", "user")
            content = msg_dict.get("content", "")
            
            # Skip system messages (handled separately)
            if role == "system":
                continue
            
            # Map 'assistant' role
            if role not in ("user", "assistant"):
                role = "user"
            
            formatted.append({
                "role": role,
                "content": content
            })
        
        return formatted
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
