"""
Groq Provider - Schnelle Inferenz für Cheap Tier
===============================================

Verwendet Groq für schnelle, günstige Anfragen.
Llama 3.1 8B für einfache Erklärungen und Router.
"""

import logging
from typing import Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class GroqProvider:
    """
    Groq provider for fast, cheap inference.
    
    Features:
    - Llama 3.1 8B for cheap tier
    - Very fast inference (~100ms)
    - Low cost (~$0.05/1M tokens)
    - Good for simple queries and routing
    """
    
    def __init__(
        self,
        api_key: str,
        default_model: str = "llama-3.1-8b-instant",
        max_tokens: int = 2048,
        timeout: float = 30.0
    ):
        self.api_key = api_key
        self.default_model = default_model
        self.max_tokens = max_tokens
        
        self._client = httpx.AsyncClient(
            base_url="https://api.groq.com/openai/v1",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=timeout
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5)
    )
    async def generate(
        self,
        messages: list,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7,
        system_prompt: str = None
    ) -> dict:
        """
        Generate response using Groq.
        
        Args:
            messages: Conversation messages
            model: Model to use (default: llama-3.1-8b-instant)
            max_tokens: Max output tokens
            temperature: Sampling temperature
            system_prompt: Optional system prompt
            
        Returns:
            dict with content, usage, model
        """
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        # Format messages
        formatted_messages = self._format_messages(messages, system_prompt)
        
        # Make request
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": formatted_messages
            }
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Extract content
        content = data["choices"][0]["message"]["content"]
        
        # Extract usage
        usage = data.get("usage", {})
        usage_info = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }
        
        return {
            "content": content,
            "usage": usage_info,
            "model": model,
            "finish_reason": data["choices"][0].get("finish_reason")
        }
    
    async def generate_stream(
        self,
        messages: list,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7
    ):
        """
        Generate streaming response.
        
        Yields content chunks as they arrive.
        """
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        formatted_messages = self._format_messages(messages)
        
        async with self._client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": formatted_messages,
                "stream": True
            }
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
                        
                        delta = event["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                            
                    except json.JSONDecodeError:
                        continue
    
    def _format_messages(
        self,
        messages: list,
        system_prompt: str = None
    ) -> list:
        """Format messages for OpenAI-compatible API."""
        formatted = []
        
        # Add system prompt if provided
        if system_prompt:
            formatted.append({
                "role": "system",
                "content": system_prompt
            })
        
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
            
            # Validate role
            if role not in ("system", "user", "assistant"):
                role = "user"
            
            formatted.append({
                "role": role,
                "content": content
            })
        
        return formatted
    
    async def health_check(self) -> bool:
        """Check if Groq API is reachable."""
        try:
            response = await self._client.get("/models")
            return response.status_code == 200
        except Exception:
            return False
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
