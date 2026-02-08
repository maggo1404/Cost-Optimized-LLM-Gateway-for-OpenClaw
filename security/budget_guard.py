"""
Budget Guard - Daily Cost Limits
================================

Verfolgt tägliche Ausgaben und erzwingt Budget-Limits.
Drei Stufen: Soft (Warnung) → Medium (Throttle) → Hard (Block)
"""

import time
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BudgetStatus:
    """Current budget status."""
    daily_spent: float
    daily_limit: float
    soft_limit: float
    medium_limit: float
    hard_limit: float
    level: str  # normal, soft, medium, hard
    remaining: float
    reset_at: str


class BudgetGuard:
    """
    Daily budget guard with progressive limits.
    
    Levels:
    - NORMAL: Under soft limit, full speed
    - SOFT: Over soft limit, warning logged
    - MEDIUM: Over medium limit, premium throttled
    - HARD: Over hard limit, all blocked
    """
    
    def __init__(
        self,
        soft_limit: float = 5.0,
        medium_limit: float = 15.0,
        hard_limit: float = 50.0,
        db_path: str = "budget.db"
    ):
        self.soft_limit = soft_limit
        self.medium_limit = medium_limit
        self.hard_limit = hard_limit
        self.db_path = db_path
        
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database for tracking."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spending (
                date TEXT PRIMARY KEY,
                total_cost REAL DEFAULT 0,
                request_count INTEGER DEFAULT 0,
                cheap_cost REAL DEFAULT 0,
                premium_cost REAL DEFAULT 0,
                cache_hits INTEGER DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                date TEXT NOT NULL,
                cost REAL NOT NULL,
                tier TEXT,
                model TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER
            )
        """)
        self.conn.commit()
    
    def _get_today(self) -> str:
        """Get today's date string."""
        return date.today().isoformat()
    
    def _ensure_today_record(self):
        """Ensure today's spending record exists."""
        today = self._get_today()
        self.conn.execute(
            "INSERT OR IGNORE INTO spending (date) VALUES (?)",
            (today,)
        )
        self.conn.commit()
    
    def get_daily_spent(self) -> float:
        """Get total spent today."""
        self._ensure_today_record()
        today = self._get_today()
        
        cursor = self.conn.execute(
            "SELECT total_cost FROM spending WHERE date = ?",
            (today,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0.0
    
    def check(
        self,
        estimated_cost: float,
        tier: str = "premium"
    ) -> dict:
        """
        Check if request is allowed under budget.
        
        Args:
            estimated_cost: Estimated cost for request
            tier: Request tier (cheap, premium)
            
        Returns:
            dict with allowed, level, reason, etc.
        """
        daily_spent = self.get_daily_spent()
        projected = daily_spent + estimated_cost
        
        # Hard limit - block everything
        if projected > self.hard_limit:
            logger.error(f"Budget HARD limit reached: ${daily_spent:.2f}/${self.hard_limit:.2f}")
            return {
                "allowed": False,
                "level": "hard",
                "reason": f"Daily budget exceeded (${daily_spent:.2f}/${self.hard_limit:.2f})",
                "daily_spent": daily_spent,
                "limit": self.hard_limit
            }
        
        # Medium limit - block premium, allow cheap
        if projected > self.medium_limit:
            if tier == "premium":
                logger.warning(f"Budget MEDIUM limit: blocking premium (${daily_spent:.2f})")
                return {
                    "allowed": False,
                    "level": "medium",
                    "reason": f"Premium blocked (budget ${daily_spent:.2f}/${self.medium_limit:.2f})",
                    "daily_spent": daily_spent,
                    "limit": self.medium_limit,
                    "suggest_tier": "cheap"
                }
        
        # Soft limit - allow but warn
        if projected > self.soft_limit:
            logger.info(f"Budget SOFT limit reached: ${daily_spent:.2f}/${self.soft_limit:.2f}")
            return {
                "allowed": True,
                "level": "soft",
                "reason": f"Approaching limit (${daily_spent:.2f}/${self.soft_limit:.2f})",
                "daily_spent": daily_spent,
                "limit": self.soft_limit
            }
        
        # Normal operation
        return {
            "allowed": True,
            "level": "normal",
            "reason": "Within budget",
            "daily_spent": daily_spent,
            "limit": self.hard_limit
        }
    
    def record_spend(
        self,
        cost: float,
        tier: str = "premium",
        model: str = None,
        tokens_in: int = 0,
        tokens_out: int = 0
    ):
        """
        Record spending for today.
        
        Args:
            cost: Actual cost of request
            tier: Request tier
            model: Model used
            tokens_in: Input tokens
            tokens_out: Output tokens
        """
        self._ensure_today_record()
        today = self._get_today()
        now = datetime.now().isoformat()
        
        # Update daily total
        if tier == "cheap":
            self.conn.execute(
                """
                UPDATE spending 
                SET total_cost = total_cost + ?, 
                    request_count = request_count + 1,
                    cheap_cost = cheap_cost + ?
                WHERE date = ?
                """,
                (cost, cost, today)
            )
        else:
            self.conn.execute(
                """
                UPDATE spending 
                SET total_cost = total_cost + ?, 
                    request_count = request_count + 1,
                    premium_cost = premium_cost + ?
                WHERE date = ?
                """,
                (cost, cost, today)
            )
        
        # Record transaction
        self.conn.execute(
            """
            INSERT INTO transactions 
            (timestamp, date, cost, tier, model, tokens_in, tokens_out)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, today, cost, tier, model, tokens_in, tokens_out)
        )
        
        self.conn.commit()
        
        logger.debug(f"Recorded spend: ${cost:.4f} ({tier})")
    
    def record_cache_hit(self):
        """Record a cache hit (no cost)."""
        self._ensure_today_record()
        today = self._get_today()
        
        self.conn.execute(
            "UPDATE spending SET cache_hits = cache_hits + 1 WHERE date = ?",
            (today,)
        )
        self.conn.commit()
    
    def get_status(self) -> dict:
        """Get current budget status."""
        self._ensure_today_record()
        today = self._get_today()
        
        cursor = self.conn.execute(
            """
            SELECT total_cost, request_count, cheap_cost, premium_cost, cache_hits
            FROM spending WHERE date = ?
            """,
            (today,)
        )
        row = cursor.fetchone()
        
        daily_spent = row[0] if row else 0
        
        # Determine level
        if daily_spent >= self.hard_limit:
            level = "hard"
        elif daily_spent >= self.medium_limit:
            level = "medium"
        elif daily_spent >= self.soft_limit:
            level = "soft"
        else:
            level = "normal"
        
        return {
            "date": today,
            "daily_spent": round(daily_spent, 4),
            "request_count": row[1] if row else 0,
            "cheap_cost": round(row[2], 4) if row else 0,
            "premium_cost": round(row[3], 4) if row else 0,
            "cache_hits": row[4] if row else 0,
            "level": level,
            "limits": {
                "soft": self.soft_limit,
                "medium": self.medium_limit,
                "hard": self.hard_limit
            },
            "remaining": round(self.hard_limit - daily_spent, 4),
            "reset_at": f"{today}T24:00:00"
        }
    
    def get_history(self, days: int = 7) -> list:
        """Get spending history for past N days."""
        cursor = self.conn.execute(
            """
            SELECT date, total_cost, request_count, cheap_cost, premium_cost, cache_hits
            FROM spending
            ORDER BY date DESC
            LIMIT ?
            """,
            (days,)
        )
        
        return [
            {
                "date": row[0],
                "total_cost": round(row[1], 4),
                "request_count": row[2],
                "cheap_cost": round(row[3], 4),
                "premium_cost": round(row[4], 4),
                "cache_hits": row[5]
            }
            for row in cursor.fetchall()
        ]
    
    def adjust_limits(
        self,
        soft: Optional[float] = None,
        medium: Optional[float] = None,
        hard: Optional[float] = None
    ):
        """Adjust budget limits (for admin)."""
        if soft is not None:
            self.soft_limit = soft
        if medium is not None:
            self.medium_limit = medium
        if hard is not None:
            self.hard_limit = hard
        
        logger.info(f"Budget limits adjusted: soft=${self.soft_limit}, medium=${self.medium_limit}, hard=${self.hard_limit}")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
