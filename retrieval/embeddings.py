"""
Embedding Service - Vector Embeddings für Semantic Search
========================================================

Generiert Embeddings für Semantic Cache.
Verwendet Anthropic Voyage oder OpenAI als Fallback.
Lokaler Cache für häufige Queries.
"""

import os
import json
import hashlib
import logging
from typing import Optional
import numpy as np
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Embedding service with caching and fallback.
    
    Features:
    - Anthropic Voyage embeddings (primary)
    - OpenAI embeddings (fallback)
    - Local disk cache
    - Batching support
    """
    
    def __init__(
        self,
        anthropic_key: str = "",
        openai_key: str = "",
        cache_dir: str = "/tmp/embeddings_cache",
        model: str = "voyage-code-2",  # Good for code
        dimension: int = 1024
    ):
        self.anthropic_key = anthropic_key
        self.openai_key = openai_key
        self.cache_dir = cache_dir
        self.model = model
        self.dimension = dimension
        
        # Create cache directory
        os.makedirs(cache_dir, exist_ok=True)
        
        # HTTP clients
        self._voyage_client = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={
                "Authorization": f"Bearer {anthropic_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        ) if anthropic_key else None
        
        self._openai_client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        ) if openai_key else None
    
    async def embed(self, text: str) -> Optional[np.ndarray]:
        """
        Generate embedding for text.
        
        Args:
            text: Text to embed
            
        Returns:
            Numpy array of embedding or None if failed
        """
        # Check cache first
        cached = self._get_cached(text)
        if cached is not None:
            return cached
        
        # Try Voyage (Anthropic) first
        if self._voyage_client:
            try:
                embedding = await self._embed_voyage(text)
                if embedding is not None:
                    self._cache_embedding(text, embedding)
                    return embedding
            except Exception as e:
                logger.warning(f"Voyage embedding failed: {e}")
        
        # Fallback to OpenAI
        if self._openai_client:
            try:
                embedding = await self._embed_openai(text)
                if embedding is not None:
                    self._cache_embedding(text, embedding)
                    return embedding
            except Exception as e:
                logger.warning(f"OpenAI embedding failed: {e}")
        
        # Last resort: simple hash-based pseudo-embedding
        logger.warning("All embedding providers failed, using hash-based fallback")
        return self._hash_embedding(text)
    
    async def embed_batch(self, texts: list[str]) -> list[Optional[np.ndarray]]:
        """Embed multiple texts (with batching for efficiency)."""
        results = []
        
        # Check cache for each
        uncached_indices = []
        uncached_texts = []
        
        for i, text in enumerate(texts):
            cached = self._get_cached(text)
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)
                uncached_indices.append(i)
                uncached_texts.append(text)
        
        # Batch embed uncached
        if uncached_texts:
            if self._voyage_client:
                try:
                    embeddings = await self._embed_voyage_batch(uncached_texts)
                    for i, emb in zip(uncached_indices, embeddings):
                        results[i] = emb
                        if emb is not None:
                            self._cache_embedding(texts[i], emb)
                    return results
                except Exception as e:
                    logger.warning(f"Voyage batch failed: {e}")
            
            # Fallback: embed individually
            for i, text in zip(uncached_indices, uncached_texts):
                results[i] = await self.embed(text)
        
        return results
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5))
    async def _embed_voyage(self, text: str) -> Optional[np.ndarray]:
        """Embed using Voyage AI (Anthropic partner)."""
        response = await self._voyage_client.post(
            "/embeddings",
            json={
                "model": self.model,
                "input": text,
                "input_type": "query"
            }
        )
        response.raise_for_status()
        
        data = response.json()
        embedding = data["data"][0]["embedding"]
        return np.array(embedding, dtype=np.float32)
    
    async def _embed_voyage_batch(self, texts: list[str]) -> list[Optional[np.ndarray]]:
        """Batch embed using Voyage."""
        response = await self._voyage_client.post(
            "/embeddings",
            json={
                "model": self.model,
                "input": texts,
                "input_type": "query"
            }
        )
        response.raise_for_status()
        
        data = response.json()
        return [
            np.array(item["embedding"], dtype=np.float32)
            for item in data["data"]
        ]
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5))
    async def _embed_openai(self, text: str) -> Optional[np.ndarray]:
        """Embed using OpenAI (fallback)."""
        response = await self._openai_client.post(
            "/embeddings",
            json={
                "model": "text-embedding-3-small",
                "input": text
            }
        )
        response.raise_for_status()
        
        data = response.json()
        embedding = data["data"][0]["embedding"]
        return np.array(embedding, dtype=np.float32)
    
    def _hash_embedding(self, text: str) -> np.ndarray:
        """
        Generate deterministic pseudo-embedding from text hash.
        
        This is a fallback when no API is available.
        Quality is much lower than real embeddings.
        """
        # Create hash
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        
        # Convert hash to floats
        embedding = np.zeros(self.dimension, dtype=np.float32)
        for i in range(min(len(text_hash) // 2, self.dimension)):
            byte_val = int(text_hash[i*2:i*2+2], 16)
            embedding[i] = (byte_val - 128) / 128.0
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def _get_cache_path(self, text: str) -> str:
        """Get cache file path for text."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        return os.path.join(self.cache_dir, f"{text_hash}.npy")
    
    def _get_cached(self, text: str) -> Optional[np.ndarray]:
        """Get embedding from cache."""
        cache_path = self._get_cache_path(text)
        
        if os.path.exists(cache_path):
            try:
                return np.load(cache_path)
            except Exception as e:
                logger.warning(f"Cache read error: {e}")
        
        return None
    
    def _cache_embedding(self, text: str, embedding: np.ndarray):
        """Cache embedding to disk."""
        cache_path = self._get_cache_path(text)
        
        try:
            np.save(cache_path, embedding)
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    def clear_cache(self):
        """Clear embedding cache."""
        import shutil
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir)
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        if not os.path.exists(self.cache_dir):
            return {"entries": 0, "size_mb": 0}
        
        files = os.listdir(self.cache_dir)
        total_size = sum(
            os.path.getsize(os.path.join(self.cache_dir, f))
            for f in files if f.endswith('.npy')
        )
        
        return {
            "entries": len(files),
            "size_mb": round(total_size / (1024 * 1024), 2)
        }
    
    async def close(self):
        """Close HTTP clients."""
        if self._voyage_client:
            await self._voyage_client.aclose()
        if self._openai_client:
            await self._openai_client.aclose()
