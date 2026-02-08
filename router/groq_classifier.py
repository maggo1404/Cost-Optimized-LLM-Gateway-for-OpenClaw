"""
Groq Classifier - Intent Classification mit Llama 8B
====================================================

Verwendet Groq's schnelle Inferenz für Router-Entscheidungen.
3x schneller als lokales Ollama, kein RAM-Overhead.
"""

import logging
from typing import Optional
from enum import Enum

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class IntentTier(str, Enum):
    CACHE_ONLY = "CACHE_ONLY"  # Zu vage, nur Cache prüfen
    LOCAL = "LOCAL"           # Kann lokal/günstig beantwortet werden
    CHEAP = "CHEAP"           # Haiku-tier (einfache Erklärungen)
    PREMIUM = "PREMIUM"       # Sonnet-tier (komplexe Analyse, Code-Gen)


class ClassificationResult:
    def __init__(
        self,
        tier: IntentTier,
        confidence: float,
        reason: str,
        complexity_score: float = 0.5,
        requires_code: bool = False,
        requires_analysis: bool = False
    ):
        self.tier = tier
        self.confidence = confidence
        self.reason = reason
        self.complexity_score = complexity_score
        self.requires_code = requires_code
        self.requires_analysis = requires_analysis


CLASSIFIER_PROMPT = """Du bist ein Query-Router für einen AI Coding Assistant. 
Klassifiziere die Anfrage in eine der folgenden Kategorien:

CACHE_ONLY: Zu vage oder unklar. Beispiele: "hilf mir", "code", "fix it"
LOCAL: Triviale Fragen, Definitionen. Beispiele: "was ist eine Variable?", "git status erklären"
CHEAP: Einfache Erklärungen, kleine Code-Snippets. Beispiele: "for-loop in Python", "regex für Email"
PREMIUM: Komplexe Analyse, große Code-Generierung, Refactoring, Debugging. Beispiele: "refactore diese Klasse", "finde den Bug in diesem Code", "implementiere Feature X"

Query: {query}

Kontext (falls vorhanden): {context}

Antworte NUR im Format:
TIER: <CACHE_ONLY|LOCAL|CHEAP|PREMIUM>
CONFIDENCE: <0.0-1.0>
REASON: <kurze Begründung>
REQUIRES_CODE: <true|false>
REQUIRES_ANALYSIS: <true|false>
COMPLEXITY: <0.0-1.0>"""


class GroqClassifier:
    """Intent classifier using Groq's fast inference."""
    
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout: float = 5.0
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://api.groq.com/openai/v1"
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=timeout
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2)
    )
    async def classify(
        self,
        query: str,
        context: Optional[dict] = None
    ) -> ClassificationResult:
        """
        Classify query intent using Groq.
        
        Args:
            query: User's query
            context: Optional context (file paths, git state, etc.)
            
        Returns:
            ClassificationResult with tier and metadata
        """
        # Quick heuristics for obvious cases
        quick_result = self._quick_classify(query)
        if quick_result:
            return quick_result
        
        # Format context for prompt
        context_str = self._format_context(context) if context else "Kein zusätzlicher Kontext"
        
        prompt = CLASSIFIER_PROMPT.format(query=query, context=context_str)
        
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 150,
                    "temperature": 0
                }
            )
            response.raise_for_status()
            
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            return self._parse_response(content)
            
        except httpx.TimeoutException:
            logger.warning("Groq timeout, falling back to CHEAP tier")
            return ClassificationResult(
                tier=IntentTier.CHEAP,
                confidence=0.5,
                reason="Router timeout - defaulting to cheap tier"
            )
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return ClassificationResult(
                tier=IntentTier.CHEAP,
                confidence=0.3,
                reason=f"Classification error: {str(e)}"
            )
    
    def _quick_classify(self, query: str) -> Optional[ClassificationResult]:
        """Quick heuristics for obvious cases."""
        query_lower = query.lower().strip()
        
        # Too vague
        vague_patterns = [
            "hilf", "help", "code", "fix", "mach", "do it",
            "kannst du", "can you", "bitte", "please"
        ]
        if len(query_lower) < 15 and any(p in query_lower for p in vague_patterns):
            return ClassificationResult(
                tier=IntentTier.CACHE_ONLY,
                confidence=0.9,
                reason="Query zu vage für sinnvolle Antwort"
            )
        
        # Obvious premium patterns
        premium_patterns = [
            "refactor", "debug", "implementier", "implement",
            "architecture", "design pattern", "optimize",
            "review", "analyse", "analyze", "komplexe",
            "umfangreich", "complete", "full", "entire"
        ]
        if any(p in query_lower for p in premium_patterns):
            return ClassificationResult(
                tier=IntentTier.PREMIUM,
                confidence=0.85,
                reason="Query enthält Premium-Indikatoren",
                requires_code=True,
                requires_analysis=True,
                complexity_score=0.8
            )
        
        # Obvious cheap patterns
        cheap_patterns = [
            "was ist", "what is", "erkläre", "explain",
            "definition", "beispiel", "example", "syntax",
            "wie schreibt man", "how to write"
        ]
        if any(p in query_lower for p in cheap_patterns):
            return ClassificationResult(
                tier=IntentTier.CHEAP,
                confidence=0.85,
                reason="Einfache Erklärung/Definition",
                complexity_score=0.3
            )
        
        return None
    
    def _format_context(self, context: dict) -> str:
        """Format context for prompt."""
        parts = []
        
        if "file_path" in context:
            parts.append(f"Datei: {context['file_path']}")
        if "language" in context:
            parts.append(f"Sprache: {context['language']}")
        if "git_status" in context:
            parts.append(f"Git: {context['git_status']}")
        if "code_snippet" in context:
            snippet = context["code_snippet"][:200]
            parts.append(f"Code: {snippet}...")
            
        return " | ".join(parts) if parts else "Kein Kontext"
    
    def _parse_response(self, content: str) -> ClassificationResult:
        """Parse LLM response into ClassificationResult."""
        lines = content.strip().split("\n")
        
        tier = IntentTier.CHEAP  # Default
        confidence = 0.5
        reason = "Parsed from response"
        requires_code = False
        requires_analysis = False
        complexity = 0.5
        
        for line in lines:
            line = line.strip()
            if line.startswith("TIER:"):
                tier_str = line.split(":", 1)[1].strip().upper()
                try:
                    tier = IntentTier(tier_str)
                except ValueError:
                    tier = IntentTier.CHEAP
                    
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                except ValueError:
                    confidence = 0.5
                    
            elif line.startswith("REASON:"):
                reason = line.split(":", 1)[1].strip()
                
            elif line.startswith("REQUIRES_CODE:"):
                requires_code = "true" in line.lower()
                
            elif line.startswith("REQUIRES_ANALYSIS:"):
                requires_analysis = "true" in line.lower()
                
            elif line.startswith("COMPLEXITY:"):
                try:
                    complexity = float(line.split(":", 1)[1].strip())
                except ValueError:
                    complexity = 0.5
        
        return ClassificationResult(
            tier=tier,
            confidence=confidence,
            reason=reason,
            requires_code=requires_code,
            requires_analysis=requires_analysis,
            complexity_score=complexity
        )
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
