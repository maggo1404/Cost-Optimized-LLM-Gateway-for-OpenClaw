"""
Rate Limiter - Token-aware Rate Limiting
========================================

Begrenzt Requests pro Minute UND Tokens pro Minute.
Verwendet Sliding Window für faire Verteilung.
"""

import time
import logging
from collections import deque
from typing import Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RateBucket:
    """Sliding window bucket for rate limiting."""
    window_seconds: int = 60
    requests: deque = field(default_factory=deque)
    tokens: deque = field(default_factory=deque)
    
    def cleanup(self, now: float):
        """Remove entries outside the window."""
        cutoff = now - self.window_seconds
        
        while self.requests and self.requests[0][0] < cutoff:
            self.requests.popleft()
        
        while self.tokens and self.tokens[0][0] < cutoff:
            self.tokens.popleft()
    
    def request_count(self) -> int:
        """Get current request count in window."""
        return len(self.requests)
    
    def token_count(self) -> int:
        """Get current token count in window."""
        return sum(t[1] for t in self.tokens)
    
    def add(self, tokens: int):
        """Add a request with token count."""
        now = time.time()
        self.requests.append((now, 1))
        self.tokens.append((now, tokens))


class RateLimiter:
    """
    Token-aware rate limiter with sliding window.
    
    Features:
    - Requests per minute limit
    - Tokens per minute limit
    - Per-tier limits
    - Sliding window for fairness
    """
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        tokens_per_minute: int = 100000,
        window_seconds: int = 60
    ):
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self.window_seconds = window_seconds
        
        # Per-tier buckets
        self.buckets = {
            "global": RateBucket(window_seconds=window_seconds),
            "cheap": RateBucket(window_seconds=window_seconds),
            "premium": RateBucket(window_seconds=window_seconds)
        }
        
        # Tier-specific limits (multipliers of base)
        self.tier_limits = {
            "global": {"requests": 1.0, "tokens": 1.0},
            "cheap": {"requests": 2.0, "tokens": 1.5},  # More lenient for cheap
            "premium": {"requests": 0.5, "tokens": 0.5}  # Stricter for premium
        }
    
    def check(
        self,
        estimated_tokens: int,
        tier: str = "global"
    ) -> Tuple[bool, str]:
        """
        Check if request is allowed under rate limits.
        
        Args:
            estimated_tokens: Estimated token count for request
            tier: Request tier (global, cheap, premium)
            
        Returns:
            Tuple of (allowed: bool, message: str)
        """
        now = time.time()
        
        # Get or create bucket for tier
        if tier not in self.buckets:
            tier = "global"
        
        bucket = self.buckets[tier]
        global_bucket = self.buckets["global"]
        
        # Cleanup old entries
        bucket.cleanup(now)
        global_bucket.cleanup(now)
        
        # Get limits for tier
        limits = self.tier_limits.get(tier, self.tier_limits["global"])
        rpm_limit = int(self.requests_per_minute * limits["requests"])
        tpm_limit = int(self.tokens_per_minute * limits["tokens"])
        
        # Check request count
        current_requests = bucket.request_count()
        if current_requests >= rpm_limit:
            wait_time = self._calculate_wait_time(bucket.requests, now)
            logger.warning(f"Rate limit (requests): {current_requests}/{rpm_limit}")
            return False, f"Request limit exceeded ({current_requests}/{rpm_limit}). Retry in {wait_time:.1f}s"
        
        # Check token count
        current_tokens = bucket.token_count()
        if current_tokens + estimated_tokens > tpm_limit:
            wait_time = self._calculate_wait_time(bucket.tokens, now)
            logger.warning(f"Rate limit (tokens): {current_tokens}/{tpm_limit}")
            return False, f"Token limit exceeded ({current_tokens}/{tpm_limit}). Retry in {wait_time:.1f}s"
        
        # Also check global limits
        global_requests = global_bucket.request_count()
        global_tokens = global_bucket.token_count()
        
        if global_requests >= self.requests_per_minute:
            wait_time = self._calculate_wait_time(global_bucket.requests, now)
            return False, f"Global request limit exceeded. Retry in {wait_time:.1f}s"
        
        if global_tokens + estimated_tokens > self.tokens_per_minute:
            wait_time = self._calculate_wait_time(global_bucket.tokens, now)
            return False, f"Global token limit exceeded. Retry in {wait_time:.1f}s"
        
        return True, "OK"
    
    def record(self, tokens: int, tier: str = "global"):
        """Record a successful request."""
        if tier not in self.buckets:
            tier = "global"
        
        self.buckets[tier].add(tokens)
        self.buckets["global"].add(tokens)
    
    def _calculate_wait_time(self, entries: deque, now: float) -> float:
        """Calculate time until oldest entry expires."""
        if not entries:
            return 0.0
        
        oldest = entries[0][0]
        wait = (oldest + self.window_seconds) - now
        return max(0.0, wait)
    
    def get_status(self) -> dict:
        """Get current rate limiter status."""
        now = time.time()
        
        status = {}
        for tier, bucket in self.buckets.items():
            bucket.cleanup(now)
            limits = self.tier_limits.get(tier, self.tier_limits["global"])
            
            status[tier] = {
                "requests": {
                    "current": bucket.request_count(),
                    "limit": int(self.requests_per_minute * limits["requests"])
                },
                "tokens": {
                    "current": bucket.token_count(),
                    "limit": int(self.tokens_per_minute * limits["tokens"])
                }
            }
        
        return status
    
    def reset(self, tier: str = None):
        """Reset rate limiter (for testing/admin)."""
        if tier:
            if tier in self.buckets:
                self.buckets[tier] = RateBucket(window_seconds=self.window_seconds)
        else:
            for t in self.buckets:
                self.buckets[t] = RateBucket(window_seconds=self.window_seconds)
