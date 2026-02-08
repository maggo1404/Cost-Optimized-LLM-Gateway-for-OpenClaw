"""
Exact Cache - SHA-256 Hash-basiertes Caching
============================================

Schneller Cache für identische Anfragen.
Verwendet SHA-256 Hash von Query + Context als Key.
"""

import json
import hashlib
import logging
import time
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)


class ExactCache:
    """
    Exact match cache using SHA-256 hashing.
    
    Features:
    - Fast O(1) lookup
    - TTL-based expiration
    - Idempotency key support
    - Context-aware hashing (includes file state, git info)
    """
    
    def __init__(
        self,
        db_path: str = "exact_cache.db",
        default_ttl: int = 3600 * 24,  # 24 hours
        max_entries: int = 10000
    ):
        self.db_path = db_path
        self.default_ttl = default_ttl
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
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                usage_json TEXT,
                idempotency_key TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                hit_count INTEGER DEFAULT 0,
                last_hit_at INTEGER
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_idempotency 
            ON cache(idempotency_key) WHERE idempotency_key IS NOT NULL
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_expires 
            ON cache(expires_at)
        """)
        await db.commit()
    
    def compute_key(
        self,
        messages: list,
        context: Optional[dict] = None
    ) -> str:
        """
        Compute cache key from messages and context.
        
        The key includes:
        - Message content and roles
        - Context (file paths, git state, etc.)
        - Working tree fingerprint (if provided)
        """
        key_parts = []
        
        # Add messages
        for msg in messages:
            if hasattr(msg, "model_dump"):
                key_parts.append(json.dumps(msg.model_dump(), sort_keys=True))
            elif hasattr(msg, "dict"):
                key_parts.append(json.dumps(msg.dict(), sort_keys=True))
            elif isinstance(msg, dict):
                key_parts.append(json.dumps(msg, sort_keys=True))
            else:
                key_parts.append(f"{msg.role}:{msg.content}")
        
        # Add context
        if context:
            # Sort context for deterministic hashing
            sorted_context = dict(sorted(context.items()))
            key_parts.append(json.dumps(sorted_context, sort_keys=True))
        
        # Compute SHA-256
        combined = "|".join(key_parts)
        return hashlib.sha256(combined.encode()).hexdigest()
    
    async def get(self, cache_key: str) -> Optional[str]:
        """
        Get cached response by key.
        
        Returns None if not found or expired.
        """
        db = await self._get_db()
        now = int(time.time())
        
        async with db.execute(
            """
            SELECT response FROM cache 
            WHERE cache_key = ? AND expires_at > ?
            """,
            (cache_key, now)
        ) as cursor:
            row = await cursor.fetchone()
        
        if row:
            # Update hit count
            await db.execute(
                """
                UPDATE cache SET hit_count = hit_count + 1, last_hit_at = ?
                WHERE cache_key = ?
                """,
                (now, cache_key)
            )
            await db.commit()
            return row[0]
        
        return None
    
    async def get_by_idempotency_key(self, idempotency_key: str) -> Optional[str]:
        """Get cached response by idempotency key."""
        db = await self._get_db()
        now = int(time.time())
        
        async with db.execute(
            """
            SELECT response FROM cache 
            WHERE idempotency_key = ? AND expires_at > ?
            """,
            (idempotency_key, now)
        ) as cursor:
            row = await cursor.fetchone()
        
        return row[0] if row else None
    
    async def set(
        self,
        cache_key: str,
        response: str,
        usage: Optional[dict] = None,
        ttl: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ):
        """
        Store response in cache.
        
        Args:
            cache_key: SHA-256 hash key
            response: Response content to cache
            usage: Token usage information
            ttl: Time-to-live in seconds (default: 24h)
            idempotency_key: Optional idempotency key
        """
        db = await self._get_db()
        now = int(time.time())
        expires_at = now + (ttl or self.default_ttl)
        
        usage_json = json.dumps(usage) if usage else None
        
        await db.execute(
            """
            INSERT OR REPLACE INTO cache 
            (cache_key, response, usage_json, idempotency_key, created_at, expires_at, hit_count, last_hit_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (cache_key, response, usage_json, idempotency_key, now, expires_at)
        )
        await db.commit()
        
        # Cleanup if needed
        await self._maybe_cleanup()
    
    async def invalidate(self, cache_key: str):
        """Invalidate a specific cache entry."""
        db = await self._get_db()
        await db.execute("DELETE FROM cache WHERE cache_key = ?", (cache_key,))
        await db.commit()
    
    async def invalidate_by_pattern(self, pattern: str):
        """Invalidate cache entries matching a pattern (for file-based invalidation)."""
        db = await self._get_db()
        # Note: This requires storing the original context, which we could add
        # For now, this is a placeholder for event-driven invalidation
        logger.info(f"Pattern invalidation requested: {pattern}")
    
    async def _maybe_cleanup(self):
        """Cleanup expired entries and enforce max size."""
        db = await self._get_db()
        now = int(time.time())
        
        # Remove expired entries
        await db.execute("DELETE FROM cache WHERE expires_at < ?", (now,))
        
        # Check entry count
        async with db.execute("SELECT COUNT(*) FROM cache") as cursor:
            count = (await cursor.fetchone())[0]
        
        # If over limit, remove oldest entries
        if count > self.max_entries:
            to_remove = count - self.max_entries + 100  # Remove extra buffer
            await db.execute(
                """
                DELETE FROM cache WHERE cache_key IN (
                    SELECT cache_key FROM cache 
                    ORDER BY last_hit_at ASC NULLS FIRST, created_at ASC
                    LIMIT ?
                )
                """,
                (to_remove,)
            )
        
        await db.commit()
    
    async def get_stats(self) -> dict:
        """Get cache statistics."""
        db = await self._get_db()
        now = int(time.time())
        
        async with db.execute("SELECT COUNT(*) FROM cache") as cursor:
            total = (await cursor.fetchone())[0]
        
        async with db.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at > ?", (now,)
        ) as cursor:
            active = (await cursor.fetchone())[0]
        
        async with db.execute(
            "SELECT SUM(hit_count) FROM cache"
        ) as cursor:
            total_hits = (await cursor.fetchone())[0] or 0
        
        return {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": total - active,
            "total_hits": total_hits
        }
    
    async def close(self):
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
