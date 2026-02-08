"""
Metrics Collector - Gateway Monitoring
=====================================

Sammelt Metriken für Monitoring und Alerting.
Prometheus-kompatibles Format.
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class MetricsBucket:
    """Time-windowed metrics bucket."""
    window_seconds: int = 60
    counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latencies: List[float] = field(default_factory=list)
    costs: List[float] = field(default_factory=list)
    last_reset: float = field(default_factory=time.time)
    
    def maybe_reset(self):
        """Reset if window expired."""
        now = time.time()
        if now - self.last_reset > self.window_seconds:
            self.counts = defaultdict(int)
            self.latencies = []
            self.costs = []
            self.last_reset = now


class MetricsCollector:
    """
    Metrics collector for gateway monitoring.
    
    Tracks:
    - Request counts by tier and status
    - Cache hit rates
    - Latencies (p50, p95, p99)
    - Costs by tier
    - Error rates
    """
    
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        
        # Current window metrics
        self.current = MetricsBucket(window_seconds=window_seconds)
        
        # Lifetime totals
        self.totals = {
            "requests": 0,
            "cache_hits": defaultdict(int),
            "cache_misses": defaultdict(int),
            "routing": defaultdict(int),
            "blocked": defaultdict(int),
            "errors": defaultdict(int),
            "cost": 0.0,
            "cost_by_tier": defaultdict(float)
        }
        
        # Latency histogram buckets (ms)
        self.latency_buckets = [10, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        self.latency_histogram = defaultdict(int)
    
    def record_request(self, latency_ms: float, tier: str, status: str = "success"):
        """Record a completed request."""
        self.current.maybe_reset()
        
        self.totals["requests"] += 1
        self.current.counts["requests"] += 1
        self.current.counts[f"requests_{tier}"] += 1
        self.current.counts[f"requests_{status}"] += 1
        self.current.latencies.append(latency_ms)
        
        # Update latency histogram
        for bucket in self.latency_buckets:
            if latency_ms <= bucket:
                self.latency_histogram[bucket] += 1
                break
        else:
            self.latency_histogram["inf"] += 1
    
    def record_cache_hit(self, cache_type: str):
        """Record a cache hit (exact, semantic, idempotency)."""
        self.current.maybe_reset()
        
        self.totals["cache_hits"][cache_type] += 1
        self.current.counts[f"cache_hit_{cache_type}"] += 1
    
    def record_cache_miss(self, cache_type: str):
        """Record a cache miss."""
        self.current.maybe_reset()
        
        self.totals["cache_misses"][cache_type] += 1
        self.current.counts[f"cache_miss_{cache_type}"] += 1
    
    def record_routing(self, tier: str):
        """Record a routing decision."""
        self.current.maybe_reset()
        
        self.totals["routing"][tier] += 1
        self.current.counts[f"routing_{tier}"] += 1
    
    def record_blocked(self, reason: str):
        """Record a blocked request."""
        self.current.maybe_reset()
        
        self.totals["blocked"][reason] += 1
        self.current.counts[f"blocked_{reason}"] += 1
    
    def record_error(self, error_type: str):
        """Record an error."""
        self.current.maybe_reset()
        
        self.totals["errors"][error_type] += 1
        self.current.counts[f"error_{error_type}"] += 1
    
    def record_cost(self, cost: float, tier: str):
        """Record cost for a request."""
        self.current.maybe_reset()
        
        self.totals["cost"] += cost
        self.totals["cost_by_tier"][tier] += cost
        self.current.costs.append(cost)
    
    def get_summary(self) -> dict:
        """Get metrics summary."""
        self.current.maybe_reset()
        
        # Calculate cache hit rate
        total_hits = sum(self.totals["cache_hits"].values())
        total_misses = sum(self.totals["cache_misses"].values())
        total_cache = total_hits + total_misses
        cache_hit_rate = total_hits / total_cache if total_cache > 0 else 0
        
        # Calculate latency percentiles
        latencies = sorted(self.current.latencies) if self.current.latencies else [0]
        p50 = self._percentile(latencies, 50)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)
        
        # Calculate routing distribution
        total_routed = sum(self.totals["routing"].values())
        routing_pct = {
            tier: (count / total_routed * 100) if total_routed > 0 else 0
            for tier, count in self.totals["routing"].items()
        }
        
        return {
            "window": {
                "seconds": self.window_seconds,
                "requests": self.current.counts["requests"],
                "latency_ms": {
                    "p50": round(p50, 1),
                    "p95": round(p95, 1),
                    "p99": round(p99, 1),
                    "avg": round(sum(self.current.latencies) / len(self.current.latencies), 1) if self.current.latencies else 0
                },
                "cost": round(sum(self.current.costs), 4)
            },
            "totals": {
                "requests": self.totals["requests"],
                "cost": round(self.totals["cost"], 4),
                "cost_by_tier": {k: round(v, 4) for k, v in self.totals["cost_by_tier"].items()}
            },
            "cache": {
                "hit_rate": round(cache_hit_rate * 100, 1),
                "hits_by_type": dict(self.totals["cache_hits"]),
                "misses_by_type": dict(self.totals["cache_misses"])
            },
            "routing": {
                "counts": dict(self.totals["routing"]),
                "percentages": {k: round(v, 1) for k, v in routing_pct.items()}
            },
            "blocked": dict(self.totals["blocked"]),
            "errors": dict(self.totals["errors"]),
            "latency_histogram": dict(self.latency_histogram)
        }
    
    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        lines = []
        summary = self.get_summary()
        
        # Request counter
        lines.append(f'# HELP gateway_requests_total Total requests')
        lines.append(f'# TYPE gateway_requests_total counter')
        lines.append(f'gateway_requests_total {summary["totals"]["requests"]}')
        
        # Cost counter
        lines.append(f'# HELP gateway_cost_total Total cost in USD')
        lines.append(f'# TYPE gateway_cost_total counter')
        lines.append(f'gateway_cost_total {summary["totals"]["cost"]}')
        
        # Cost by tier
        for tier, cost in summary["totals"]["cost_by_tier"].items():
            lines.append(f'gateway_cost_by_tier{{tier="{tier}"}} {cost}')
        
        # Cache hit rate
        lines.append(f'# HELP gateway_cache_hit_rate Cache hit rate')
        lines.append(f'# TYPE gateway_cache_hit_rate gauge')
        lines.append(f'gateway_cache_hit_rate {summary["cache"]["hit_rate"] / 100}')
        
        # Latency histogram
        lines.append(f'# HELP gateway_latency_ms Request latency in ms')
        lines.append(f'# TYPE gateway_latency_ms histogram')
        for bucket, count in self.latency_histogram.items():
            lines.append(f'gateway_latency_ms_bucket{{le="{bucket}"}} {count}')
        
        # Routing distribution
        for tier, count in summary["routing"]["counts"].items():
            lines.append(f'gateway_routing_total{{tier="{tier}"}} {count}')
        
        # Blocked requests
        for reason, count in summary["blocked"].items():
            lines.append(f'gateway_blocked_total{{reason="{reason}"}} {count}')
        
        # Errors
        for error_type, count in summary["errors"].items():
            lines.append(f'gateway_errors_total{{type="{error_type}"}} {count}')
        
        return '\n'.join(lines)
    
    def _percentile(self, data: list, percentile: int) -> float:
        """Calculate percentile of sorted data."""
        if not data:
            return 0.0
        
        k = (len(data) - 1) * percentile / 100
        f = int(k)
        c = f + 1 if f + 1 < len(data) else f
        
        return data[f] + (data[c] - data[f]) * (k - f) if f != c else data[f]
    
    def reset(self):
        """Reset all metrics."""
        self.current = MetricsBucket(window_seconds=self.window_seconds)
        self.totals = {
            "requests": 0,
            "cache_hits": defaultdict(int),
            "cache_misses": defaultdict(int),
            "routing": defaultdict(int),
            "blocked": defaultdict(int),
            "errors": defaultdict(int),
            "cost": 0.0,
            "cost_by_tier": defaultdict(float)
        }
        self.latency_histogram = defaultdict(int)
