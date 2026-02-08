"""
Local OpenAI-Compatible Provider
================================

Unterstützt lokale LLMs mit OpenAI-kompatibler API:
- Ollama
- LM Studio
- LocalAI
- vLLM
- text-generation-webui
- Eigene OpenAI-kompatible Endpunkte
"""

import logging
from typing import Optional, AsyncGenerator
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class LocalOpenAIProvider:
    """
    Provider für lokale OpenAI-kompatible APIs.
    
    Unterstützt:
    - Ollama (http://localhost:11434/v1)
    - LM Studio (http://localhost:1234/v1)
    - LocalAI (http://localhost:8080/v1)
    - vLLM (http://localhost:8000/v1)
    - Beliebige OpenAI-kompatible Endpunkte
    """
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "local",
        default_model: str = "llama3.2:latest",
        max_tokens: int = 4096,
        timeout: float = 120.0,
        verify_ssl: bool = False
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.max_tokens = max_tokens
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=timeout,
            verify=verify_ssl
        )
        
        logger.info(f"LocalOpenAIProvider initialized: {base_url}, model: {default_model}")
    
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
        system_prompt: str = None,
        stop: list = None
    ) -> dict:
        """
        Generiere Antwort vom lokalen LLM.
        
        Args:
            messages: Konversationsnachrichten
            model: Modellname (z.B. "llama3.2:latest", "mistral:7b")
            max_tokens: Max Output-Tokens
            temperature: Sampling-Temperatur
            system_prompt: Optionaler System-Prompt
            stop: Stop-Sequenzen
            
        Returns:
            dict mit content, usage, model
        """
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        formatted_messages = self._format_messages(messages, system_prompt)
        
        payload = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        if stop:
            payload["stop"] = stop
        
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            
            return {
                "content": content,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                },
                "model": model,
                "finish_reason": data["choices"][0].get("finish_reason", "stop"),
                "provider": "local"
            }
            
        except httpx.ConnectError as e:
            logger.error(f"Lokales LLM nicht erreichbar: {self.base_url} - {e}")
            raise RuntimeError(f"Lokales LLM nicht erreichbar: {self.base_url}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP-Fehler vom lokalen LLM: {e.response.status_code}")
            raise
    
    async def generate_stream(
        self,
        messages: list,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """Streaming-Antwort vom lokalen LLM."""
        model = model or self.default_model
        max_tokens = max_tokens or self.max_tokens
        
        formatted_messages = self._format_messages(messages)
        
        async with self._client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": model,
                "messages": formatted_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
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
                    except:
                        continue
    
    def _format_messages(self, messages: list, system_prompt: str = None) -> list:
        """Formatiere Nachrichten für OpenAI-API."""
        formatted = []
        
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        
        for msg in messages:
            if hasattr(msg, "model_dump"):
                msg_dict = msg.model_dump()
            elif hasattr(msg, "dict"):
                msg_dict = msg.dict()
            elif isinstance(msg, dict):
                msg_dict = msg
            else:
                msg_dict = {"role": str(msg.role), "content": str(msg.content)}
            
            role = msg_dict.get("role", "user")
            if role not in ("system", "user", "assistant"):
                role = "user"
            
            formatted.append({
                "role": role,
                "content": msg_dict.get("content", "")
            })
        
        return formatted
    
    async def list_models(self) -> list:
        """Liste verfügbare Modelle."""
        try:
            response = await self._client.get("/models")
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.warning(f"Modell-Liste nicht abrufbar: {e}")
            return []
    
    async def health_check(self) -> dict:
        """Prüfe Verfügbarkeit des lokalen LLMs."""
        try:
            response = await self._client.get("/models")
            if response.status_code == 200:
                models = response.json().get("data", [])
                return {
                    "status": "ok",
                    "base_url": self.base_url,
                    "models_available": len(models),
                    "default_model": self.default_model
                }
        except httpx.ConnectError:
            return {
                "status": "offline",
                "base_url": self.base_url,
                "error": "Verbindung fehlgeschlagen"
            }
        except Exception as e:
            return {
                "status": "error",
                "base_url": self.base_url,
                "error": str(e)
            }
    
    async def close(self):
        """Schließe HTTP-Client."""
        await self._client.aclose()
