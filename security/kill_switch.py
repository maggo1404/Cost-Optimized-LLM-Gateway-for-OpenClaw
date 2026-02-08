"""
Kill Switch - Emergency Service Control
======================================

Globaler Notschalter für das Gateway.
Drei Modi: Throttle → Degrade → Kill
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class KillSwitchMode(str, Enum):
    OFF = "off"           # Normal operation
    THROTTLE = "throttle" # Slow down requests
    DEGRADE = "degrade"   # Only cheap tier
    KILL = "kill"         # Block everything


@dataclass
class KillSwitchState:
    """Kill switch state."""
    mode: KillSwitchMode
    reason: str
    activated_at: Optional[float]
    activated_by: str  # manual, budget, error_rate


class KillSwitch:
    """
    Global kill switch for emergency service control.
    
    Modes:
    - OFF: Normal operation
    - THROTTLE: Add delays to requests (rate limiting)
    - DEGRADE: Only allow cheap tier (no premium)
    - KILL: Block all requests
    
    Automatic triggers:
    - Budget guard reaching hard limit
    - High error rate
    - Manual activation
    """
    
    def __init__(
        self,
        budget_guard=None,
        error_threshold: float = 0.5,  # 50% error rate triggers
        throttle_delay: float = 2.0     # Seconds to delay in throttle mode
    ):
        self.budget_guard = budget_guard
        self.error_threshold = error_threshold
        self.throttle_delay = throttle_delay
        
        self.state = KillSwitchState(
            mode=KillSwitchMode.OFF,
            reason="",
            activated_at=None,
            activated_by=""
        )
        
        # Error tracking
        self._recent_requests = 0
        self._recent_errors = 0
        self._last_error_check = time.time()
    
    def check(self) -> dict:
        """
        Check if requests should be blocked/throttled.
        
        Returns:
            dict with blocked, throttle_delay, mode, reason
        """
        # Check manual state first
        if self.state.mode == KillSwitchMode.KILL:
            return {
                "blocked": True,
                "mode": "kill",
                "reason": self.state.reason or "Kill switch active",
                "retry_after": 3600
            }
        
        if self.state.mode == KillSwitchMode.DEGRADE:
            return {
                "blocked": False,
                "mode": "degrade",
                "reason": "Degraded mode - only cheap tier",
                "force_tier": "cheap"
            }
        
        if self.state.mode == KillSwitchMode.THROTTLE:
            return {
                "blocked": False,
                "mode": "throttle",
                "reason": "Throttle mode active",
                "throttle_delay": self.throttle_delay
            }
        
        # Auto-checks
        
        # Check budget guard
        if self.budget_guard:
            budget_status = self.budget_guard.get_status()
            
            if budget_status["level"] == "hard":
                self._activate(KillSwitchMode.KILL, "Budget hard limit reached", "budget")
                return {
                    "blocked": True,
                    "mode": "kill",
                    "reason": "Daily budget exhausted",
                    "retry_after": self._seconds_until_midnight()
                }
            
            if budget_status["level"] == "medium":
                return {
                    "blocked": False,
                    "mode": "degrade",
                    "reason": "Budget medium limit - premium throttled",
                    "force_tier": "cheap"
                }
        
        # Check error rate
        error_rate = self._get_error_rate()
        if error_rate > self.error_threshold:
            self._activate(KillSwitchMode.THROTTLE, f"High error rate: {error_rate:.1%}", "error_rate")
            return {
                "blocked": False,
                "mode": "throttle",
                "reason": f"High error rate ({error_rate:.1%})",
                "throttle_delay": self.throttle_delay
            }
        
        # Normal operation
        return {
            "blocked": False,
            "mode": "off",
            "reason": "Normal operation"
        }
    
    def enable(self, mode: str = "kill", reason: str = "Manual activation"):
        """Manually enable kill switch."""
        try:
            kill_mode = KillSwitchMode(mode)
        except ValueError:
            kill_mode = KillSwitchMode.KILL
        
        self._activate(kill_mode, reason, "manual")
        logger.warning(f"Kill switch enabled: {mode} - {reason}")
    
    def disable(self):
        """Disable kill switch."""
        self.state = KillSwitchState(
            mode=KillSwitchMode.OFF,
            reason="",
            activated_at=None,
            activated_by=""
        )
        logger.info("Kill switch disabled")
    
    def _activate(self, mode: KillSwitchMode, reason: str, activated_by: str):
        """Activate kill switch."""
        self.state = KillSwitchState(
            mode=mode,
            reason=reason,
            activated_at=time.time(),
            activated_by=activated_by
        )
    
    def record_request(self, success: bool):
        """Record request outcome for error rate tracking."""
        now = time.time()
        
        # Reset counters every minute
        if now - self._last_error_check > 60:
            self._recent_requests = 0
            self._recent_errors = 0
            self._last_error_check = now
        
        self._recent_requests += 1
        if not success:
            self._recent_errors += 1
    
    def _get_error_rate(self) -> float:
        """Get recent error rate."""
        if self._recent_requests < 10:  # Need minimum sample
            return 0.0
        return self._recent_errors / self._recent_requests
    
    def _seconds_until_midnight(self) -> int:
        """Calculate seconds until midnight (budget reset)."""
        now = time.time()
        midnight = (int(now / 86400) + 1) * 86400  # Next midnight UTC
        return int(midnight - now)
    
    def get_status(self) -> dict:
        """Get kill switch status."""
        return {
            "mode": self.state.mode.value,
            "reason": self.state.reason,
            "activated_at": self.state.activated_at,
            "activated_by": self.state.activated_by,
            "error_rate": self._get_error_rate(),
            "recent_requests": self._recent_requests,
            "recent_errors": self._recent_errors
        }
