"""
BM25 Search - Full-Text Search mit SQLite FTS5
==============================================

Schneller Keyword-basierter Search für Cache Fast-Path.
Verwendet SQLite FTS5 für BM25-Ranking.
"""

import logging
import time
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)


class BM25Search:
    """
    BM25-based full-text search using SQLite FTS5.
    
    Features:
    - Fast keyword-based search
    - BM25 ranking
    - Query-Response index for cache lookup
    - Efficient for finding similar past queries
    """
    
    def __init__(
        self,
        db_path: str = "bm25_index.db"
    ):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
    
    async def _get_db(self) -> aiosqlite.Connection:
        """Get or create database connection."""
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            await self._init_schema()
        return self._db
    
    async def _init_schema(self):
        """Initialize FTS5 tables."""
        db = self._db
        
        # Main FTS5 table for queries
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS query_index 
            USING fts5(
                query,
                response,
                context,
                tokenize='porter unicode61'
            )
        """)
        
        # Metadata table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS query_meta (
                rowid INTEGER PRIMARY KEY,
                created_at INTEGER,
                hit_count INTEGER DEFAULT 0,
                last_hit_at INTEGER
            )
        """)
        
        await db.commit()
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5
    ) -> list[dict]:
        """
        Search for similar queries using BM25.
        
        Args:
            query: Search query
            top_k: Number of results to return
            min_score: Minimum BM25 score threshold
            
        Returns:
            List of matches with query, response, score
        """
        db = await self._get_db()
        
        # Escape special FTS5 characters
        escaped_query = self._escape_fts_query(query)
        
        try:
            async with db.execute(
                """
                SELECT 
                    query,
                    response,
                    bm25(query_index) as score,
                    rowid
                FROM query_index
                WHERE query_index MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (escaped_query, top_k)
            ) as cursor:
                rows = await cursor.fetchall()
            
            results = []
            for row in rows:
                # BM25 scores are negative (lower is better)
                # Convert to positive score (higher is better)
                raw_score = abs(row[2])
                normalized_score = min(1.0, raw_score / 10.0)  # Normalize to 0-1
                
                if normalized_score >= min_score:
                    results.append({
                        "query": row[0],
                        "response": row[1],
                        "score": normalized_score,
                        "rowid": row[3]
                    })
            
            return results
            
        except Exception as e:
            logger.warning(f"BM25 search error: {e}")
            return []
    
    async def index_query(
        self,
        query: str,
        response: str,
        context: Optional[str] = None
    ):
        """
        Index a query-response pair.
        
        Args:
            query: User's query
            response: Generated response
            context: Optional context string
        """
        db = await self._get_db()
        now = int(time.time())
        
        # Check for duplicate
        existing = await self.search(query, top_k=1, min_score=0.95)
        if existing and existing[0]["score"] > 0.98:
            # Update existing entry's hit count
            await db.execute(
                "UPDATE query_meta SET hit_count = hit_count + 1, last_hit_at = ? WHERE rowid = ?",
                (now, existing[0]["rowid"])
            )
            await db.commit()
            return
        
        # Insert new entry
        cursor = await db.execute(
            "INSERT INTO query_index (query, response, context) VALUES (?, ?, ?)",
            (query, response[:2000], context or "")  # Limit response length
        )
        rowid = cursor.lastrowid
        
        # Insert metadata
        await db.execute(
            "INSERT INTO query_meta (rowid, created_at) VALUES (?, ?)",
            (rowid, now)
        )
        
        await db.commit()
    
    async def get_frequent_queries(self, limit: int = 20) -> list[dict]:
        """Get most frequently hit queries."""
        db = await self._get_db()
        
        async with db.execute(
            """
            SELECT qi.query, qi.response, qm.hit_count, qm.last_hit_at
            FROM query_index qi
            JOIN query_meta qm ON qi.rowid = qm.rowid
            ORDER BY qm.hit_count DESC
            LIMIT ?
            """,
            (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
        
        return [
            {
                "query": row[0],
                "response": row[1][:200] + "..." if len(row[1]) > 200 else row[1],
                "hit_count": row[2],
                "last_hit_at": row[3]
            }
            for row in rows
        ]
    
    def _escape_fts_query(self, query: str) -> str:
        """
        Escape special FTS5 characters and create search query.
        
        FTS5 special chars: " * ^ : OR AND NOT ( )
        """
        # Remove special characters
        special_chars = '"*^:()[]{}|\\/'
        for char in special_chars:
            query = query.replace(char, ' ')
        
        # Split into words and filter
        words = query.split()
        words = [w for w in words if len(w) > 2]  # Remove very short words
        words = [w for w in words if w.upper() not in ('AND', 'OR', 'NOT')]
        
        if not words:
            return '""'  # Empty search
        
        # Join with OR for broader matching
        return ' OR '.join(f'"{w}"' for w in words[:10])  # Limit to 10 terms
    
    async def get_stats(self) -> dict:
        """Get index statistics."""
        db = await self._get_db()
        
        async with db.execute("SELECT COUNT(*) FROM query_index") as cursor:
            total = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT SUM(hit_count) FROM query_meta") as cursor:
            total_hits = (await cursor.fetchone())[0] or 0
        
        return {
            "indexed_queries": total,
            "total_hits": total_hits
        }
    
    async def cleanup(self, max_entries: int = 10000, max_age_days: int = 30):
        """Cleanup old entries."""
        db = await self._get_db()
        
        # Count entries
        async with db.execute("SELECT COUNT(*) FROM query_index") as cursor:
            count = (await cursor.fetchone())[0]
        
        if count <= max_entries:
            return
        
        # Remove oldest entries with low hit count
        to_remove = count - max_entries + 100
        cutoff = int(time.time()) - (max_age_days * 86400)
        
        await db.execute(
            """
            DELETE FROM query_index WHERE rowid IN (
                SELECT qi.rowid FROM query_index qi
                JOIN query_meta qm ON qi.rowid = qm.rowid
                WHERE qm.created_at < ? OR qm.hit_count = 0
                ORDER BY qm.hit_count ASC, qm.created_at ASC
                LIMIT ?
            )
            """,
            (cutoff, to_remove)
        )
        
        # Cleanup orphaned metadata
        await db.execute(
            """
            DELETE FROM query_meta WHERE rowid NOT IN (
                SELECT rowid FROM query_index
            )
            """
        )
        
        await db.commit()
    
    async def close(self):
        """Close database connection."""
        if self._db:
            await self._db.close()
            self._db = None
