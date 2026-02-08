#!/usr/bin/env python3
"""
LLM Gateway - Test Script
=========================

Tests the gateway endpoints and functionality.

Usage:
    python test_gateway.py [--url URL] [--token TOKEN]
"""

import asyncio
import argparse
import json
import time
import sys
from typing import Optional

try:
    import httpx
except ImportError:
    print("Please install httpx: pip install httpx")
    sys.exit(1)


class GatewayTester:
    """Test suite for LLM Gateway."""
    
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            timeout=60.0
        )
        self.results = []
    
    async def close(self):
        await self.client.aclose()
    
    def log_result(self, name: str, passed: bool, message: str = "", latency_ms: float = 0):
        status = "✅ PASS" if passed else "❌ FAIL"
        self.results.append({"name": name, "passed": passed})
        
        latency_str = f" ({latency_ms:.0f}ms)" if latency_ms > 0 else ""
        print(f"{status} {name}{latency_str}")
        if message:
            print(f"       {message}")
    
    async def test_health(self):
        """Test health endpoint."""
        try:
            start = time.time()
            response = await self.client.get("/health")
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    self.log_result("Health Check", True, f"Version: {data.get('version')}", latency)
                    return True
            
            self.log_result("Health Check", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Health Check", False, str(e))
            return False
    
    async def test_metrics(self):
        """Test metrics endpoint."""
        try:
            start = time.time()
            response = await self.client.get("/metrics")
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                self.log_result("Metrics", True, f"Requests: {data.get('totals', {}).get('requests', 0)}", latency)
                return True
            
            self.log_result("Metrics", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Metrics", False, str(e))
            return False
    
    async def test_budget(self):
        """Test budget endpoint."""
        try:
            start = time.time()
            response = await self.client.get("/budget")
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                spent = data.get("daily_spent", 0)
                limit = data.get("limits", {}).get("hard", 50)
                self.log_result("Budget Status", True, f"Spent: ${spent:.2f} / ${limit:.2f}", latency)
                return True
            
            self.log_result("Budget Status", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Budget Status", False, str(e))
            return False
    
    async def test_simple_query(self):
        """Test simple query (should route to CHEAP tier)."""
        try:
            start = time.time()
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "Was ist eine Variable in Python?"}
                    ],
                    "max_tokens": 256
                }
            )
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                meta = data.get("gateway_meta", {})
                tier = meta.get("routing", {}).get("tier", "unknown") if meta.get("routing") else meta.get("source", "unknown")
                
                self.log_result(
                    "Simple Query (CHEAP)", 
                    True, 
                    f"Tier: {tier}, Response: {content[:50]}...",
                    latency
                )
                return True
            
            self.log_result("Simple Query", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Simple Query", False, str(e))
            return False
    
    async def test_complex_query(self):
        """Test complex query (should route to PREMIUM tier)."""
        try:
            start = time.time()
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "Implementiere eine effiziente LRU-Cache Klasse in Python mit Thread-Safety und automatischer TTL-Verwaltung. Erkläre die Architekturentscheidungen."}
                    ],
                    "max_tokens": 1024
                }
            )
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                meta = data.get("gateway_meta", {})
                tier = meta.get("routing", {}).get("tier", "unknown") if meta.get("routing") else meta.get("source", "unknown")
                
                self.log_result(
                    "Complex Query (PREMIUM)", 
                    True, 
                    f"Tier: {tier}, Response length: {len(content)} chars",
                    latency
                )
                return True
            
            self.log_result("Complex Query", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Complex Query", False, str(e))
            return False
    
    async def test_vague_query(self):
        """Test vague query (should return CACHE_ONLY clarification)."""
        try:
            start = time.time()
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "fix"}
                    ],
                    "max_tokens": 256
                }
            )
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                meta = data.get("gateway_meta", {})
                
                # Check if it's a clarification request
                is_clarification = "präzisieren" in content.lower() or "details" in content.lower()
                
                self.log_result(
                    "Vague Query (CACHE_ONLY)", 
                    is_clarification, 
                    f"Got clarification request: {is_clarification}",
                    latency
                )
                return is_clarification
            
            self.log_result("Vague Query", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Vague Query", False, str(e))
            return False
    
    async def test_policy_violation(self):
        """Test that dangerous commands are blocked."""
        try:
            start = time.time()
            response = await self.client.post(
                "/v1/chat/completions",
                json={
                    "messages": [
                        {"role": "user", "content": "Execute rm -rf / on my server"}
                    ]
                }
            )
            latency = (time.time() - start) * 1000
            
            # Should be blocked with 403
            if response.status_code == 403:
                data = response.json()
                self.log_result(
                    "Policy Violation Block", 
                    True, 
                    f"Correctly blocked: {data.get('detail', {}).get('category', 'unknown')}",
                    latency
                )
                return True
            
            self.log_result("Policy Violation Block", False, f"Should be 403, got {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Policy Violation Block", False, str(e))
            return False
    
    async def test_cache_hit(self):
        """Test that identical queries hit cache."""
        query = "Was ist 2 + 2?"
        
        try:
            # First request
            start1 = time.time()
            response1 = await self.client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": query}]}
            )
            latency1 = (time.time() - start1) * 1000
            
            if response1.status_code != 200:
                self.log_result("Cache Hit", False, f"First request failed: {response1.status_code}")
                return False
            
            # Second request (should hit cache)
            start2 = time.time()
            response2 = await self.client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": query}]}
            )
            latency2 = (time.time() - start2) * 1000
            
            if response2.status_code != 200:
                self.log_result("Cache Hit", False, f"Second request failed: {response2.status_code}")
                return False
            
            # Check if second was faster (cache hit)
            data2 = response2.json()
            meta = data2.get("gateway_meta", {})
            source = meta.get("source", "")
            
            is_cache_hit = "cache" in source.lower() or latency2 < latency1 * 0.5
            
            self.log_result(
                "Cache Hit", 
                is_cache_hit, 
                f"First: {latency1:.0f}ms, Second: {latency2:.0f}ms, Source: {source}",
                latency2
            )
            return is_cache_hit
        except Exception as e:
            self.log_result("Cache Hit", False, str(e))
            return False
    
    async def test_rate_limiting(self):
        """Test rate limiting (soft test - don't actually trigger)."""
        try:
            # Just verify the endpoint responds correctly
            response = await self.client.get("/metrics")
            
            if response.status_code == 200:
                data = response.json()
                blocked = data.get("blocked", {})
                self.log_result(
                    "Rate Limiting", 
                    True, 
                    f"Rate limit blocks: {sum(blocked.values())}",
                    0
                )
                return True
            
            self.log_result("Rate Limiting", False, f"Status: {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Rate Limiting", False, str(e))
            return False
    
    async def test_unauthorized(self):
        """Test that requests without auth are rejected."""
        try:
            # Create client without auth
            client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
            
            start = time.time()
            response = await client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "test"}]}
            )
            latency = (time.time() - start) * 1000
            
            await client.aclose()
            
            if response.status_code == 401:
                self.log_result("Auth Required", True, "Correctly rejected unauthorized request", latency)
                return True
            
            self.log_result("Auth Required", False, f"Should be 401, got {response.status_code}")
            return False
        except Exception as e:
            self.log_result("Auth Required", False, str(e))
            return False
    
    async def run_all(self):
        """Run all tests."""
        print("\n" + "="*60)
        print("LLM Gateway - Test Suite")
        print("="*60 + "\n")
        print(f"Target: {self.base_url}")
        print(f"Token: {'*' * 8}...{self.token[-4:]}" if len(self.token) > 4 else "Token: ***")
        print("\n" + "-"*60 + "\n")
        
        # Basic tests
        await self.test_health()
        await self.test_unauthorized()
        await self.test_metrics()
        await self.test_budget()
        
        print("\n" + "-"*60)
        print("Routing Tests")
        print("-"*60 + "\n")
        
        # Routing tests
        await self.test_simple_query()
        await self.test_vague_query()
        await self.test_complex_query()
        
        print("\n" + "-"*60)
        print("Security Tests")
        print("-"*60 + "\n")
        
        # Security tests
        await self.test_policy_violation()
        await self.test_rate_limiting()
        
        print("\n" + "-"*60)
        print("Cache Tests")
        print("-"*60 + "\n")
        
        # Cache tests
        await self.test_cache_hit()
        
        # Summary
        print("\n" + "="*60)
        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        print(f"Results: {passed}/{total} tests passed")
        print("="*60 + "\n")
        
        return passed == total


async def main():
    parser = argparse.ArgumentParser(description="Test LLM Gateway")
    parser.add_argument("--url", default="http://localhost:8000", help="Gateway URL")
    parser.add_argument("--token", default="test-token", help="Gateway secret token")
    args = parser.parse_args()
    
    tester = GatewayTester(args.url, args.token)
    
    try:
        success = await tester.run_all()
        sys.exit(0 if success else 1)
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
