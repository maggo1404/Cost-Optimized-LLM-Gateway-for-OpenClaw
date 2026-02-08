"""
LLM Providers
=============

Anthropic, Groq, und lokale OpenAI-kompatible Endpunkte.
"""

from .anthropic_provider import AnthropicProvider
from .groq_provider import GroqProvider
from .local_openai_provider import LocalOpenAIProvider

__all__ = ["AnthropicProvider", "GroqProvider", "LocalOpenAIProvider"]
