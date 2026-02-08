"""
Utility functions for LLM Gateway.
"""

import hashlib
import time
import re
from typing import Optional


def generate_request_id() -> str:
    """Generate unique request ID."""
    return f"req_{int(time.time() * 1000)}_{hashlib.md5(str(time.time()).encode()).hexdigest()[:8]}"


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.
    
    Rough estimate: ~4 characters per token for English.
    More accurate would use tiktoken.
    """
    return len(text) // 4 + 1


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length with suffix."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def sanitize_for_logging(text: str, max_length: int = 200) -> str:
    """Sanitize text for safe logging (remove secrets, truncate)."""
    # Remove potential API keys
    patterns = [
        (r'sk-[a-zA-Z0-9]{20,}', 'sk-***'),
        (r'gsk_[a-zA-Z0-9]{20,}', 'gsk_***'),
        (r'sk-ant-[a-zA-Z0-9-]{20,}', 'sk-ant-***'),
        (r'Bearer\s+[a-zA-Z0-9_-]{20,}', 'Bearer ***'),
    ]
    
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    
    return truncate_text(result, max_length)


def format_cost(cost: float) -> str:
    """Format cost for display."""
    if cost < 0.01:
        return f"${cost:.4f}"
    elif cost < 1:
        return f"${cost:.3f}"
    else:
        return f"${cost:.2f}"


def format_duration(seconds: float) -> str:
    """Format duration for display."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}min"
    else:
        return f"{seconds / 3600:.1f}h"


def parse_model_name(model: str) -> dict:
    """Parse model name into components."""
    parts = model.lower().split("/")
    
    if len(parts) == 2:
        provider, name = parts
    else:
        provider = "unknown"
        name = model
    
    # Detect tier
    if any(x in name for x in ["opus", "gpt-4", "claude-3-opus"]):
        tier = "premium+"
    elif any(x in name for x in ["sonnet", "gpt-3.5", "claude-3-sonnet"]):
        tier = "premium"
    elif any(x in name for x in ["haiku", "llama", "mistral", "claude-3-haiku"]):
        tier = "cheap"
    else:
        tier = "unknown"
    
    return {
        "provider": provider,
        "name": name,
        "tier": tier,
        "full": model
    }


class RollingAverage:
    """Calculate rolling average over a window."""
    
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.values = []
    
    def add(self, value: float):
        self.values.append(value)
        if len(self.values) > self.window_size:
            self.values.pop(0)
    
    @property
    def average(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)
    
    @property
    def count(self) -> int:
        return len(self.values)


class CircuitBreaker:
    """
    Simple circuit breaker for external services.
    
    States:
    - CLOSED: Normal operation
    - OPEN: Failing, reject requests
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_requests: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        
        self.failures = 0
        self.successes = 0
        self.state = "CLOSED"
        self.last_failure_time: Optional[float] = None
    
    def can_execute(self) -> bool:
        """Check if request should be allowed."""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            # Check if recovery timeout passed
            if self.last_failure_time and time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.successes = 0
                return True
            return False
        
        if self.state == "HALF_OPEN":
            return self.successes < self.half_open_requests
        
        return False
    
    def record_success(self):
        """Record successful request."""
        if self.state == "HALF_OPEN":
            self.successes += 1
            if self.successes >= self.half_open_requests:
                self.state = "CLOSED"
                self.failures = 0
        else:
            self.failures = max(0, self.failures - 1)
    
    def record_failure(self):
        """Record failed request."""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
        
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
    
    def get_state(self) -> dict:
        return {
            "state": self.state,
            "failures": self.failures,
            "threshold": self.failure_threshold
        }
