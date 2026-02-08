#!/usr/bin/env python3
"""
LLM Gateway v2.0 - Kostenoptimiertes AI-Routing
===============================================

Lokales LLM + Prompt Caching + Intelligentes Routing
Unterstützt: Ollama, LM Studio, Anthropic, Groq, OpenAI
"""

import os
import time
import yaml
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from router.tier_router import TierRouter, RoutingDecision
from router.groq_classifier import GroqClassifier
from cache.exact_cache import ExactCache
from cache.semantic_cache import SemanticCache
from security.policy_gate import PolicyGate, PolicyViolation
from security.rate_limiter import RateLimiter
from security.budget_guard import BudgetGuard
from security.kill_switch import KillSwitch
from retrieval.bm25_search import BM25Search
from retrieval.embeddings import EmbeddingService
from providers.anthropic_provider import AnthropicProvider
from providers.groq_provider import GroqProvider
from providers.local_openai_provider import LocalOpenAIProvider
from monitoring.metrics import MetricsCollector
from monitoring.logger import setup_logging

# Logging Setup
setup_logging()
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Lade Konfiguration aus config.yaml oder Environment."""
    config_path = Path(os.getenv("CONFIG_PATH", "/app/config/config.yaml"))
    
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
            logger.info(f"Konfiguration geladen: {config_path}")
            return config
    
    # Fallback: Environment-Variablen
    logger.info("Keine config.yaml gefunden, verwende Environment-Variablen")
    return {}


class Settings:
    def __init__(self, config: dict = None):
        config = config or {}
        
        # Server
        self.GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", 
            config.get("server", {}).get("secret", "change-me-in-production"))
        
        # API Keys
        providers = config.get("providers", {})
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY", 
            providers.get("groq", {}).get("api_key", ""))
        self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", 
            providers.get("anthropic", {}).get("api_key", ""))
        self.ANTHROPIC_SETUP_TOKEN = os.getenv("ANTHROPIC_SETUP_TOKEN",
            providers.get("anthropic", {}).get("setup_token", ""))
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", 
            providers.get("openai", {}).get("api_key", ""))
        
        # Local LLM
        local = providers.get("local", {})
        self.LOCAL_LLM_ENABLED = os.getenv("LOCAL_LLM_ENABLED", 
            str(local.get("enabled", True))).lower() == "true"
        self.LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", 
            local.get("base_url", "http://host.docker.internal:11434/v1"))
        self.LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", 
            local.get("api_key", "local"))
        self.LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", 
            local.get("default_model", "llama3.2:latest"))
        
        # Budget Limits
        budget = config.get("budget", {}).get("daily", {})
        self.DAILY_BUDGET_SOFT = float(os.getenv("DAILY_BUDGET_SOFT", 
            budget.get("soft", 5.0)))
        self.DAILY_BUDGET_MEDIUM = float(os.getenv("DAILY_BUDGET_MEDIUM", 
            budget.get("medium", 15.0)))
        self.DAILY_BUDGET_HARD = float(os.getenv("DAILY_BUDGET_HARD", 
            budget.get("hard", 50.0)))
        
        # Rate Limits
        rate = config.get("rate_limits", {})
        self.RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", 
            rate.get("requests_per_minute", 60)))
        self.RATE_LIMIT_TPM = int(os.getenv("RATE_LIMIT_TPM", 
            rate.get("tokens_per_minute", 100000)))
        
        # Cache
        cache = config.get("caching", {})
        self.CACHE_DIR = os.getenv("CACHE_DIR", 
            cache.get("data_dir", "/app/data"))
        self.SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", 
            cache.get("semantic", {}).get("similarity_threshold", 0.92)))
        
        # Context Budgets
        routing = config.get("routing", {}).get("tiers", {})
        self.CONTEXT_BUDGET_CHEAP = int(os.getenv("CONTEXT_BUDGET_CHEAP", 
            routing.get("cheap", {}).get("context_budget", 4000)))
        self.CONTEXT_BUDGET_PREMIUM = int(os.getenv("CONTEXT_BUDGET_PREMIUM", 
            routing.get("premium", {}).get("context_budget", 16000)))
        
        # Routing
        self.ROUTER_PROVIDER = os.getenv("ROUTER_PROVIDER",
            config.get("routing", {}).get("router_provider", "local"))


config = load_config()
settings = Settings(config)

# Global instances
policy_gate: PolicyGate = None
rate_limiter: RateLimiter = None
budget_guard: BudgetGuard = None
kill_switch: KillSwitch = None
exact_cache: ExactCache = None
semantic_cache: SemanticCache = None
groq_classifier: GroqClassifier = None
tier_router: TierRouter = None
bm25_search: BM25Search = None
embedding_service: EmbeddingService = None
anthropic_provider: AnthropicProvider = None
groq_provider: GroqProvider = None
local_provider: LocalOpenAIProvider = None
metrics: MetricsCollector = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources."""
    global policy_gate, rate_limiter, budget_guard, kill_switch
    global exact_cache, semantic_cache, groq_classifier, tier_router
    global bm25_search, embedding_service, anthropic_provider, groq_provider
    global local_provider, metrics
    
    logger.info("🚀 Starting LLM Gateway v2.0...")
    
    os.makedirs(settings.CACHE_DIR, exist_ok=True)
    
    # Security
    policy_gate = PolicyGate()
    rate_limiter = RateLimiter(
        requests_per_minute=settings.RATE_LIMIT_RPM,
        tokens_per_minute=settings.RATE_LIMIT_TPM
    )
    budget_guard = BudgetGuard(
        soft_limit=settings.DAILY_BUDGET_SOFT,
        medium_limit=settings.DAILY_BUDGET_MEDIUM,
        hard_limit=settings.DAILY_BUDGET_HARD,
        db_path=f"{settings.CACHE_DIR}/budget.db"
    )
    kill_switch = KillSwitch(budget_guard)
    
    # Caching
    exact_cache = ExactCache(db_path=f"{settings.CACHE_DIR}/exact_cache.db")
    embedding_service = EmbeddingService(
        anthropic_key=settings.ANTHROPIC_API_KEY,
        openai_key=settings.OPENAI_API_KEY,
        cache_dir=settings.CACHE_DIR
    )
    semantic_cache = SemanticCache(
        embedding_service=embedding_service,
        db_path=f"{settings.CACHE_DIR}/semantic_cache.db",
        similarity_threshold=settings.SEMANTIC_THRESHOLD
    )
    
    # Retrieval
    bm25_search = BM25Search(db_path=f"{settings.CACHE_DIR}/bm25_index.db")
    
    # Local LLM Provider
    if settings.LOCAL_LLM_ENABLED:
        local_provider = LocalOpenAIProvider(
            base_url=settings.LOCAL_LLM_URL,
            api_key=settings.LOCAL_LLM_API_KEY,
            default_model=settings.LOCAL_LLM_MODEL
        )
        local_health = await local_provider.health_check()
        if local_health["status"] == "ok":
            logger.info(f"✅ Lokales LLM verbunden: {settings.LOCAL_LLM_URL}")
        else:
            logger.warning(f"⚠️ Lokales LLM nicht erreichbar: {local_health}")
    
    # Cloud Providers
    if settings.GROQ_API_KEY:
        groq_provider = GroqProvider(api_key=settings.GROQ_API_KEY)
        groq_classifier = GroqClassifier(api_key=settings.GROQ_API_KEY)
    
    if settings.ANTHROPIC_API_KEY:
        anthropic_provider = AnthropicProvider(api_key=settings.ANTHROPIC_API_KEY)
    
    # Routing
    tier_router = TierRouter(
        classifier=groq_classifier,
        bm25_search=bm25_search,
        context_budget_cheap=settings.CONTEXT_BUDGET_CHEAP,
        context_budget_premium=settings.CONTEXT_BUDGET_PREMIUM,
        local_provider=local_provider,
        router_provider=settings.ROUTER_PROVIDER
    )
    
    # Monitoring
    metrics = MetricsCollector()
    
    logger.info("✅ All components initialized")
    logger.info(f"📊 Routing via: {settings.ROUTER_PROVIDER}")
    logger.info(f"💾 Cache: {settings.CACHE_DIR}")
    
    yield
    
    logger.info("🛑 Shutting down LLM Gateway...")
    if local_provider:
        await local_provider.close()
    await exact_cache.close()
    await semantic_cache.close()
    await bm25_search.close()
    budget_guard.close()


app = FastAPI(
    title="LLM Gateway",
    version="2.0.0",
    description="Kostenoptimiertes AI-Routing für OpenClaw mit lokalem LLM",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dashboard Static Files
dashboard_path = Path(__file__).parent / "dashboard" / "dist"
if dashboard_path.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")


# Request/Response Models
class Message(BaseModel):
    role: str = Field(..., description="Role: user, assistant, system")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., description="Conversation messages")
    model: Optional[str] = Field(None, description="Requested model")
    temperature: Optional[float] = Field(0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(4096, ge=1, le=32000)
    stream: Optional[bool] = Field(False)
    context: Optional[dict] = Field(None)
    force_tier: Optional[str] = Field(None, description="Force tier: local, cheap, premium")
    idempotency_key: Optional[str] = Field(None)


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[dict]
    usage: dict
    gateway_meta: Optional[dict] = None


# Auth
async def verify_auth(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization header")
    
    token = auth_header[7:]
    if token != settings.GATEWAY_SECRET:
        raise HTTPException(401, "Invalid API key")
    
    return token


# Endpoints
@app.get("/health")
async def health():
    local_status = None
    if local_provider:
        local_status = await local_provider.health_check()
    
    return {
        "status": "ok",
        "version": "2.0.0",
        "components": {
            "policy_gate": policy_gate is not None,
            "cache": exact_cache is not None,
            "router": tier_router is not None,
            "local_llm": local_status,
            "anthropic": anthropic_provider is not None,
            "groq": groq_provider is not None
        }
    }


@app.get("/api/metrics")
async def get_metrics(token: str = Depends(verify_auth)):
    return metrics.get_summary()


@app.get("/api/budget")
async def get_budget(token: str = Depends(verify_auth)):
    return budget_guard.get_status()


@app.get("/api/local/models")
async def list_local_models(token: str = Depends(verify_auth)):
    """Liste verfügbare lokale Modelle."""
    if not local_provider:
        raise HTTPException(503, "Lokales LLM nicht konfiguriert")
    
    models = await local_provider.list_models()
    return {"models": models}


@app.post("/admin/kill-switch")
async def toggle_kill_switch(action: str, token: str = Depends(verify_auth)):
    if action == "enable":
        kill_switch.enable()
        return {"status": "enabled"}
    elif action == "disable":
        kill_switch.disable()
        return {"status": "disabled"}
    elif action == "status":
        return kill_switch.get_status()
    else:
        raise HTTPException(400, "Invalid action")


@app.post("/v1/chat/completions", response_model=ChatResponse)
async def chat_completions(request: ChatRequest, token: str = Depends(verify_auth)):
    """Main chat completions endpoint."""
    start_time = time.time()
    request_id = f"req_{int(time.time() * 1000)}"
    user_message = request.messages[-1].content if request.messages else ""
    
    try:
        # 1. Policy Gate
        violation = policy_gate.check(user_message)
        if violation:
            metrics.record_blocked("policy_violation")
            raise HTTPException(403, {"error": "policy_violation", "category": violation.category})
        
        # 2. Kill Switch
        kill_status = kill_switch.check()
        if kill_status["blocked"]:
            metrics.record_blocked("kill_switch")
            raise HTTPException(503, {"error": "service_unavailable", "reason": kill_status["reason"]})
        
        # 3. Rate Limiting
        estimated_tokens = sum(len(m.content) for m in request.messages) // 4 + 100
        rate_ok, rate_msg = rate_limiter.check(estimated_tokens)
        if not rate_ok:
            metrics.record_blocked("rate_limit")
            raise HTTPException(429, {"error": "rate_limit", "message": rate_msg})
        
        # 4. Exact Cache
        cache_key = exact_cache.compute_key(request.messages, request.context)
        exact_hit = await exact_cache.get(cache_key)
        if exact_hit:
            metrics.record_cache_hit("exact")
            return create_response(exact_hit, request_id, "exact_cache", start_time)
        
        # 5. Route request
        routing = await tier_router.route(
            query=user_message,
            messages=request.messages,
            context=request.context,
            force_tier=request.force_tier
        )
        
        # 6. Generate based on tier
        if routing.tier == "LOCAL" and local_provider:
            response = await local_provider.generate(
                messages=routing.compressed_messages or request.messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature
            )
            actual_model = f"local/{settings.LOCAL_LLM_MODEL}"
            metrics.record_routing("local")
            actual_cost = 0  # Lokal = kostenlos
            
        elif routing.tier == "CHEAP":
            provider = local_provider if local_provider else groq_provider
            if not provider:
                raise HTTPException(503, "Kein Provider für CHEAP tier verfügbar")
            
            response = await provider.generate(
                messages=routing.compressed_messages or request.messages,
                max_tokens=request.max_tokens,
                temperature=request.temperature
            )
            actual_model = response.get("model", "cheap")
            metrics.record_routing("cheap")
            actual_cost = 0 if provider == local_provider else calculate_cost(response["usage"], actual_model)
            
        else:  # PREMIUM
            if not anthropic_provider:
                raise HTTPException(503, "Anthropic nicht konfiguriert")
            
            response = await anthropic_provider.generate(
                messages=routing.compressed_messages or request.messages,
                model="claude-sonnet-4-20250514",
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                use_cache=True
            )
            actual_model = "claude-sonnet-4-20250514"
            metrics.record_routing("premium")
            actual_cost = calculate_cost(response["usage"], actual_model)
        
        # Record cost
        budget_guard.record_spend(actual_cost)
        metrics.record_cost(actual_cost, routing.tier)
        
        # Cache response
        await exact_cache.set(cache_key, response["content"], response["usage"])
        
        return create_response(
            response["content"],
            request_id,
            actual_model,
            start_time,
            usage=response["usage"],
            routing_info=routing
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Request {request_id} failed: {e}")
        metrics.record_error(str(type(e).__name__))
        raise HTTPException(500, {"error": "internal_error", "message": str(e)})


def calculate_cost(usage: dict, model: str) -> float:
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    
    if "claude" in model.lower():
        regular_input = input_tokens - cache_read
        return (regular_input / 1_000_000) * 3.0 + (cache_read / 1_000_000) * 0.30 + (output_tokens / 1_000_000) * 15.0
    else:
        return (input_tokens + output_tokens) / 1_000_000 * 0.05


def create_response(content: str, request_id: str, model: str, start_time: float, 
                   usage: dict = None, routing_info: RoutingDecision = None) -> ChatResponse:
    return ChatResponse(
        id=request_id,
        created=int(time.time()),
        model=model,
        choices=[{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        gateway_meta={
            "latency_ms": int((time.time() - start_time) * 1000),
            "source": model,
            "routing": routing_info.model_dump() if routing_info else None
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=os.getenv("ENV") == "development")
