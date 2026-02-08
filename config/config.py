"""
Configuration Management
========================

Lädt Konfiguration aus Environment-Variablen.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


def load_env():
    """Load environment variables from .env file."""
    # Try multiple locations
    env_paths = [
        Path(".env"),
        Path("/opt/llm-gateway/.env"),
        Path.home() / ".llm-gateway" / ".env"
    ]
    
    for path in env_paths:
        if path.exists():
            load_dotenv(path)
            return str(path)
    
    return None


@dataclass
class Settings:
    """Gateway configuration settings."""
    
    # API Keys
    groq_api_key: str
    anthropic_api_key: str
    openai_api_key: str
    gateway_secret: str
    
    # Budget Limits
    daily_budget_soft: float
    daily_budget_medium: float
    daily_budget_hard: float
    
    # Rate Limits
    rate_limit_rpm: int
    rate_limit_tpm: int
    
    # Cache
    cache_dir: str
    semantic_threshold: float
    
    # Context Budgets
    context_budget_cheap: int
    context_budget_premium: int
    
    # Server
    host: str
    port: int
    env: str
    
    # Logging
    log_level: str
    log_format: str
    log_file: Optional[str]
    
    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment."""
        load_env()
        
        return cls(
            # API Keys
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            gateway_secret=os.getenv("GATEWAY_SECRET", "change-me"),
            
            # Budget Limits
            daily_budget_soft=float(os.getenv("DAILY_BUDGET_SOFT", "5.0")),
            daily_budget_medium=float(os.getenv("DAILY_BUDGET_MEDIUM", "15.0")),
            daily_budget_hard=float(os.getenv("DAILY_BUDGET_HARD", "50.0")),
            
            # Rate Limits
            rate_limit_rpm=int(os.getenv("RATE_LIMIT_RPM", "60")),
            rate_limit_tpm=int(os.getenv("RATE_LIMIT_TPM", "100000")),
            
            # Cache
            cache_dir=os.getenv("CACHE_DIR", "/opt/llm-gateway/data"),
            semantic_threshold=float(os.getenv("SEMANTIC_THRESHOLD", "0.92")),
            
            # Context Budgets
            context_budget_cheap=int(os.getenv("CONTEXT_BUDGET_CHEAP", "4000")),
            context_budget_premium=int(os.getenv("CONTEXT_BUDGET_PREMIUM", "16000")),
            
            # Server
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            env=os.getenv("ENV", "production"),
            
            # Logging
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_format=os.getenv("LOG_FORMAT", "json"),
            log_file=os.getenv("LOG_FILE")
        )
    
    def validate(self) -> list[str]:
        """Validate settings and return list of errors."""
        errors = []
        
        if not self.groq_api_key:
            errors.append("GROQ_API_KEY is required")
        
        if not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is required")
        
        if self.gateway_secret == "change-me":
            errors.append("GATEWAY_SECRET must be changed from default")
        
        if self.daily_budget_soft >= self.daily_budget_medium:
            errors.append("DAILY_BUDGET_SOFT must be less than DAILY_BUDGET_MEDIUM")
        
        if self.daily_budget_medium >= self.daily_budget_hard:
            errors.append("DAILY_BUDGET_MEDIUM must be less than DAILY_BUDGET_HARD")
        
        return errors
    
    def to_dict(self) -> dict:
        """Convert to dictionary (hiding secrets)."""
        return {
            "groq_api_key": "***" if self.groq_api_key else "(not set)",
            "anthropic_api_key": "***" if self.anthropic_api_key else "(not set)",
            "openai_api_key": "***" if self.openai_api_key else "(not set)",
            "gateway_secret": "***" if self.gateway_secret != "change-me" else "(default)",
            "daily_budget_soft": self.daily_budget_soft,
            "daily_budget_medium": self.daily_budget_medium,
            "daily_budget_hard": self.daily_budget_hard,
            "rate_limit_rpm": self.rate_limit_rpm,
            "rate_limit_tpm": self.rate_limit_tpm,
            "cache_dir": self.cache_dir,
            "semantic_threshold": self.semantic_threshold,
            "context_budget_cheap": self.context_budget_cheap,
            "context_budget_premium": self.context_budget_premium,
            "host": self.host,
            "port": self.port,
            "env": self.env,
            "log_level": self.log_level
        }


# Global settings instance
settings = Settings.from_env()
