"""
Semantic Cache - Embedding-basiertes Similarity Caching
======================================================

Findet ähnliche Queries basierend auf semantischer Ähnlichkeit.
Verwendet Embeddings mit cosine similarity.
"""

import json
import logging
import time
import numpy as np
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)


class SemanticCache:
    """
    Semantic similarity cache using embeddings.
    
    Features:
    - Cosine similarity search
    - Risk-based verification decisions
    - Context-aware matching
    - Efficient vector storage in SQLite
    """
    
    def __init__(
        self,
        embedding_service,
        db_path: str = "semantic_cache.db",
        similarity_threshold: float = 0.92,
        max_entries: int = 5000
    ):
        self.embedding_service = embedding_service
        self.db_path = db_path
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self._db: Optional[aiosqlite.Connection] = None
    
    async def _get_db(self) -> aiosqlite.Connection:
        """Get or create database connection."""
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            await self._init_schema()
        return self._db
    
    async def _init_schema(self):
        """Initialize database schema."""
        db = self._db
        await db.execute("""
            CREATE TABLE IF NOT EXISTS semantic_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                embedding BLOB NOT NULL,
                response TEXT NOT NULL,
                context_json TEXT,
                risk_score REAL DEFAULT 0.5,
                created_at INTEGER NOT NULL,
                hit_count INTEGER DEFAULT 0,
                last_hit_at INTEGER,
                verified_count INTEGER DEFAULT 0,
                invalid_count INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_query_hash 
            ON semantic_cache(query_hash)
        """)
        await db.commit()
    
    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
        top_k: int = 3
    ) -> Optional[dict]:
        """
        Search for semantically similar cached queries.
        
        Args:
            query: User's query
            context: Optional context for filtering
            top_k: Number of candidates to consider
            
        Returns:
            Best match with response and risk score, or None
        """
        db = await self._get_db()
        
        # Get query embedding
        query_embedding = await self.embedding_service.embed(query)
        if query_embedding is None:
            return None
        
        # Fetch candidates
        async with db.execute(
            """
            SELECT id, query, embedding, response, context_json, risk_score, 
                   verified_count, invalid_count
            FROM semantic_cache
            ORDER BY created_at DESC
            LIMIT 1000
            """
        ) as cursor:
            candidates = await cursor.fetchall()
        
        if not candidates:
            return None
        
        # Calculate similarities
        best_match = None
        best_score = 0.0
        
        for row in candidates:
            id_, cached_query, emb_blob, response, ctx_json, risk_score, verified, invalid = row
            
            # Deserialize embedding
            cached_embedding = np.frombuffer(emb_blob, dtype=np.float32)
            
            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, cached_embedding)
            
            # Context matching bonus
            if context and ctx_json:
                cached_context = json.loads(ctx_json)
                context_bonus = self._context_similarity(context, cached_context)
                similarity = similarity * 0.8 + context_bonus * 0.2
            
            # Verification history adjustment
            if verified + invalid > 0:
                validity_ratio = verified / (verified + invalid)
                similarity *= (0.8 + 0.2 * validity_ratio)
            
            if similarity > best_score:
                best_score = similarity
                best_match = {
                    "id": id_,
                    "query": cached_query,
                    "response": response,
                    "score": similarity,
                    "risk_score": risk_score,
                    "context": json.loads(ctx_json) if ctx_json else None
                }
        
        # Return if above threshold
        if best_match and best_score >= self.similarity_threshold:
            # Update hit count
            await db.execute(
                """
                UPDATE semantic_cache 
                SET hit_count = hit_count + 1, last_hit_at = ?
                WHERE id = ?
                """,
                (int(time.time()), best_match["id"])
            )
            await db.commit()
            
            logger.info(f"Semantic cache hit: score={best_score:.3f}, risk={best_match['risk_score']:.2f}")
            return best_match
        
        return None
    
    async def store(
        self,
        query: str,
        response: str,
        context: Optional[dict] = None,
        risk_score: float = 0.5
    ):
        """
        Store query-response pair with embedding.
        
        Args:
            query: Original query
            response: Generated response
            context: Optional context
            risk_score: Risk score for verification decisions
        """
        db = await self._get_db()
        
        # Get embedding
        embedding = await self.embedding_service.embed(query)
        if embedding is None:
            logger.warning("Failed to generate embedding, skipping semantic cache storage")
            return
        
        # Serialize embedding
        emb_blob = embedding.astype(np.float32).tobytes()
        
        # Hash for quick duplicate check
        query_hash = hash(query) & 0xFFFFFFFF  # 32-bit hash
        
        # Context JSON
        ctx_json = json.dumps(context) if context else None
        
        now = int(time.time())
        
        await db.execute(
            """
            INSERT INTO semantic_cache 
            (query, query_hash, embedding, response, context_json, risk_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (query, str(query_hash), emb_blob, response, ctx_json, risk_score, now)
        )
        await db.commit()
        
        # Cleanup if needed
        await self._maybe_cleanup()
    
    async def record_verification(self, cache_id: int, is_valid: bool):
        """Record verification result for a cached entry."""
        db = await self._get_db()
        
        if is_valid:
            await db.execute(
                "UPDATE semantic_cache SET verified_count = verified_count + 1 WHERE id = ?",
                (cache_id,)
            )
        else:
            await db.execute(
                "UPDATE semantic_cache SET invalid_count = invalid_count + 1 WHERE id = ?",
                (cache_id,)
            )
        
        await db.commit()
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def _context_similarity(self, ctx1: dict, ctx2: dict) -> float:
        """Calculate context similarity (simple key overlap)."""
        if not ctx1 or not ctx2:
            return 0.0
        
        keys1 = set(ctx1.keys())
        keys2 = set(ctx2.keys())
        
        if not keys1 or not keys2:
            return 0.0
        
        # Jaccard similarity of keys
        intersection = len(keys1 & keys2)
        union = len(keys1 | keys2)
        key_sim = intersection / union if union > 0 else 0
        
        # Value similarity for common keys
        common_keys = keys1 & keys2
        if not common_keys:
            return key_sim
        
        value_matches = sum(1 for k in common_keys if ctx1.get(k) == ctx2.get(k))
        value_sim = value_matches / len(common_keys)
        
        return 0.5 * key_sim + 0.5 * value_sim
    
    async def _maybe_cleanup(self):
        """Cleanup old entries if over limit."""
        db = await self._get_db()
        
        async with db.execute("SELECT COUNT(*) FROM semantic_cache") as cursor:
            count = (await cursor.fetchone())[0]
        
        if count > self.max_entries:
            # Remove entries with high invalid count first, then oldest
            to_remove = count - self.max_entries + 100
            await db.execute(
                """
                DELETE FROM semantic_cache WHERE id IN (
                    SELECT id FROM semantic_cache
                    ORDER BY 
                        (CASE WHEN invalid_count > verified_count THEN 0 ELSE 1 END),
                        hit_count ASC,
                        created_at ASC
                    LIMIT ?
                )
                """,
                (to_remove,)
            )
            await db.commit()
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        db = await self._get_db()
        
        async with db.execute("SELECT COUNT(*) FROM semantic_cache") as cursor:
            total = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT SUM(hit_count) FROM semantic_cache") as cursor:
            total_hits = (await cursor.fetchone())[0] or 0
        
        async with db.execute(
            "SELECT AVG(risk_score) FROM semantic_cache"
        ) as cursor:
            avg_risk = (await cursor.fetchone())[0] or 0
        
        return {
            "total_entries": total,
            "total_hits": total_hits,
            "average_risk_score": round(avg_risk, 3),
            "similarity_threshold": self.similarity_threshold
        }
    
    async def close(self):
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
