"""
Tier Router - Dreistufiges Routing mit Context Budgeting
========================================================

Routet Anfragen basierend auf Komplexität zum optimalen Tier:
- CACHE_ONLY: Zu vage, Cache prüfen oder Rückfrage
- LOCAL/CHEAP: Haiku für einfache Fragen
- PREMIUM: Sonnet mit Prompt Caching für komplexe Aufgaben
"""

import logging
from typing import Optional
from dataclasses import dataclass

from pydantic import BaseModel

from router.groq_classifier import GroqClassifier, IntentTier, ClassificationResult
from retrieval.bm25_search import BM25Search

logger = logging.getLogger(__name__)


class RoutingDecision(BaseModel):
    """Routing decision with metadata."""
    tier: str
    confidence: float
    reason: str
    risk_score: float = 0.5
    compressed_messages: Optional[list] = None
    context_tokens: int = 0
    
    class Config:
        arbitrary_types_allowed = True


@dataclass
class ContextBudget:
    """Token budget for different tiers."""
    cheap: int = 4000
    premium: int = 16000


class TierRouter:
    """
    Routes requests to appropriate tier based on complexity.
    
    Features:
    - Groq-based intent classification
    - BM25 fast-path for common queries
    - Context budgeting and compression
    - Risk scoring for verification decisions
    """
    
    def __init__(
        self,
        classifier: GroqClassifier,
        bm25_search: BM25Search,
        context_budget_cheap: int = 4000,
        context_budget_premium: int = 16000
    ):
        self.classifier = classifier
        self.bm25_search = bm25_search
        self.budget = ContextBudget(
            cheap=context_budget_cheap,
            premium=context_budget_premium
        )
    
    async def route(
        self,
        query: str,
        messages: list,
        context: Optional[dict] = None,
        force_tier: Optional[str] = None
    ) -> RoutingDecision:
        """
        Route request to appropriate tier.
        
        Args:
            query: User's query (last message content)
            messages: Full conversation history
            context: Optional context (file info, git state)
            force_tier: Force specific tier (for testing/override)
            
        Returns:
            RoutingDecision with tier and processed messages
        """
        # Force tier if specified
        if force_tier:
            tier = force_tier.upper()
            return RoutingDecision(
                tier=tier,
                confidence=1.0,
                reason=f"Forced tier: {tier}",
                risk_score=0.5 if tier == "PREMIUM" else 0.2,
                compressed_messages=self._compress_messages(messages, tier),
                context_tokens=self._count_tokens(messages)
            )
        
        # 1. BM25 Fast-Path: Check if we have highly similar cached queries
        bm25_hit = await self.bm25_search.search(query, top_k=1)
        if bm25_hit and bm25_hit[0]["score"] > 0.9:
            logger.info(f"BM25 fast-path hit: score={bm25_hit[0]['score']:.2f}")
            return RoutingDecision(
                tier="CACHE_CANDIDATE",
                confidence=bm25_hit[0]["score"],
                reason="BM25 found highly similar query",
                risk_score=0.1,
                compressed_messages=messages,
                context_tokens=self._count_tokens(messages)
            )
        
        # 2. Classify intent with Groq
        classification = await self.classifier.classify(query, context)
        
        # 3. Determine tier
        tier = classification.tier.value
        
        # 4. Calculate risk score
        risk_score = self._calculate_risk_score(classification, context)
        
        # 5. Compress messages based on tier budget
        compressed = self._compress_messages(messages, tier)
        
        # 6. Calculate context tokens
        context_tokens = self._count_tokens(compressed)
        
        return RoutingDecision(
            tier=tier,
            confidence=classification.confidence,
            reason=classification.reason,
            risk_score=risk_score,
            compressed_messages=compressed,
            context_tokens=context_tokens
        )
    
    def _calculate_risk_score(
        self,
        classification: ClassificationResult,
        context: Optional[dict]
    ) -> float:
        """
        Calculate risk score for verification decisions.
        
        Low risk (< 0.3): Skip verification
        Medium risk (0.3-0.7): Light verification
        High risk (> 0.7): Full verification required
        """
        score = 0.5  # Base score
        
        # Complexity increases risk
        score += classification.complexity_score * 0.2
        
        # Code generation increases risk
        if classification.requires_code:
            score += 0.15
        
        # Analysis increases risk
        if classification.requires_analysis:
            score += 0.1
        
        # Low confidence increases risk
        if classification.confidence < 0.7:
            score += 0.15
        
        # Context factors
        if context:
            # Modifying files increases risk
            if context.get("action") == "modify":
                score += 0.2
            # Critical paths increase risk
            if any(p in str(context.get("file_path", "")) for p in [
                "config", "secret", "key", "password", "auth",
                ".env", "credentials", "main.py", "index"
            ]):
                score += 0.15
        
        return min(1.0, max(0.0, score))
    
    def _compress_messages(
        self,
        messages: list,
        tier: str
    ) -> list:
        """
        Compress messages to fit within tier's context budget.
        
        Strategies:
        1. Keep system prompt intact
        2. Keep last N messages based on tier
        3. Summarize older messages if needed
        4. Truncate long code blocks
        """
        budget = self.budget.premium if tier == "PREMIUM" else self.budget.cheap
        
        # Convert messages to list of dicts if needed
        msg_list = []
        for m in messages:
            if hasattr(m, "model_dump"):
                msg_list.append(m.model_dump())
            elif hasattr(m, "dict"):
                msg_list.append(m.dict())
            elif isinstance(m, dict):
                msg_list.append(m)
            else:
                msg_list.append({"role": str(m.role), "content": str(m.content)})
        
        current_tokens = self._count_tokens(msg_list)
        
        # If within budget, return as-is
        if current_tokens <= budget:
            return msg_list
        
        # Strategy 1: Keep system + last N messages
        compressed = []
        system_msgs = [m for m in msg_list if m.get("role") == "system"]
        non_system = [m for m in msg_list if m.get("role") != "system"]
        
        # Always keep system messages
        compressed.extend(system_msgs)
        
        # Keep as many recent messages as fit
        remaining_budget = budget - self._count_tokens(system_msgs)
        
        for msg in reversed(non_system):
            msg_tokens = self._count_tokens([msg])
            if msg_tokens <= remaining_budget:
                compressed.insert(len(system_msgs), msg)
                remaining_budget -= msg_tokens
            else:
                # Try truncating this message
                truncated = self._truncate_message(msg, remaining_budget)
                if truncated:
                    compressed.insert(len(system_msgs), truncated)
                break
        
        logger.info(f"Compressed {current_tokens} -> {self._count_tokens(compressed)} tokens")
        return compressed
    
    def _truncate_message(self, message: dict, max_tokens: int) -> Optional[dict]:
        """Truncate a single message to fit within token budget."""
        content = message.get("content", "")
        
        # Rough estimate: 4 chars per token
        max_chars = max_tokens * 4
        
        if len(content) <= max_chars:
            return message
        
        # Truncate with indicator
        truncated_content = content[:max_chars - 50] + "\n\n[... truncated for context budget ...]"
        
        return {
            "role": message["role"],
            "content": truncated_content
        }
    
    def _count_tokens(self, messages: list) -> int:
        """
        Estimate token count for messages.
        
        Uses rough estimate: ~4 characters per token.
        For production, consider using tiktoken.
        """
        total_chars = 0
        for msg in messages:
            if isinstance(msg, dict):
                total_chars += len(str(msg.get("content", "")))
            else:
                total_chars += len(str(getattr(msg, "content", "")))
        
        # Add overhead for role tokens, formatting
        return (total_chars // 4) + (len(messages) * 4)
