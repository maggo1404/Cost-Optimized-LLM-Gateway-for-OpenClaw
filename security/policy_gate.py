"""
Hard Policy Gate - Sicherheitsfilter VOR Router
===============================================

Blockiert gefährliche Anfragen BEVOR sie geroutet werden.
Verhindert rm -rf, secret exposure, injection attacks.
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ViolationCategory(str, Enum):
    DESTRUCTIVE_COMMAND = "destructive_command"
    SECRET_EXPOSURE = "secret_exposure"
    INJECTION_ATTEMPT = "injection_attempt"
    MALICIOUS_CODE = "malicious_code"
    SENSITIVE_PATH = "sensitive_path"
    RATE_ABUSE = "rate_abuse"


@dataclass
class PolicyViolation:
    """Represents a policy violation."""
    category: ViolationCategory
    pattern: str
    severity: str  # low, medium, high, critical
    message: str


class PolicyGate:
    """
    Hard policy gate that blocks dangerous requests.
    
    Runs BEFORE routing to prevent any processing of malicious queries.
    Uses pattern matching and heuristics for fast blocking.
    """
    
    def __init__(self):
        self._init_patterns()
    
    def _init_patterns(self):
        """Initialize blocking patterns."""
        
        # Destructive commands (critical)
        self.destructive_patterns = [
            # File system destruction
            (r'\brm\s+(-[rf]+\s+)*[/~]', "rm with root/home path"),
            (r'\brm\s+-[rf]*\s+\*', "rm with wildcard"),
            (r'\brmdir\s+(-[rf]+\s+)*/', "rmdir with root path"),
            (r'>\s*/dev/sd[a-z]', "write to block device"),
            (r'\bmkfs\.', "filesystem format"),
            (r'\bdd\s+.*of=/dev/', "dd to device"),
            (r':\(\)\{.*\|.*&\s*\};:', "fork bomb"),
            
            # System destruction
            (r'\bsystemctl\s+(stop|disable)\s+(network|ssh|sshd)', "disable critical service"),
            (r'\biptables\s+-F', "flush iptables"),
            (r'\bufw\s+disable', "disable firewall"),
        ]
        
        # Secret/credential exposure (high)
        self.secret_patterns = [
            (r'cat\s+.*(/etc/shadow|/etc/passwd)', "read system credentials"),
            (r'cat\s+.*(\.env|\.ssh|id_rsa|\.aws|credentials)', "read secrets"),
            (r'echo\s+.*\$\{?(API_KEY|SECRET|PASSWORD|TOKEN)', "echo secrets"),
            (r'curl\s+.*@.*password', "curl with password"),
            (r'printenv\s+.*(SECRET|KEY|PASSWORD|TOKEN)', "print secret env"),
            (r'export\s+.*=.*\bsk-[a-zA-Z0-9]+', "export API key"),
        ]
        
        # Injection patterns (high)
        self.injection_patterns = [
            (r';\s*(rm|cat|curl|wget|bash|sh|python|perl)', "command injection"),
            (r'\|\s*(bash|sh|python|perl)', "pipe to shell"),
            (r'\$\(.*\)', "command substitution in suspicious context"),
            (r'`[^`]+`', "backtick execution"),
            (r'eval\s*\(', "eval execution"),
            (r'exec\s*\(', "exec execution"),
        ]
        
        # Malicious code patterns (high)
        self.malicious_patterns = [
            (r'base64\s+-d.*\|\s*(bash|sh)', "base64 decode to shell"),
            (r'curl\s+.*\|\s*(bash|sh)', "curl pipe to shell"),
            (r'wget\s+.*-O\s*-\s*\|\s*(bash|sh)', "wget pipe to shell"),
            (r'nc\s+-[el]+', "netcat listener"),
            (r'/dev/tcp/', "bash tcp"),
            (r'python\s+-c\s+[\'"]import\s+(socket|subprocess)', "python reverse shell"),
        ]
        
        # Sensitive paths (medium)
        self.sensitive_paths = [
            (r'/etc/sudoers', "sudoers modification"),
            (r'/etc/passwd', "passwd access"),
            (r'/etc/shadow', "shadow access"),
            (r'/root/', "root directory access"),
            (r'~root/', "root home access"),
            (r'/proc/\d+/', "process memory access"),
        ]
    
    def check(self, query: str) -> Optional[PolicyViolation]:
        """
        Check query against all policy rules.
        
        Args:
            query: User's query to check
            
        Returns:
            PolicyViolation if blocked, None if allowed
        """
        query_lower = query.lower()
        
        # Check destructive patterns (critical)
        for pattern, desc in self.destructive_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.warning(f"Destructive command blocked: {desc}")
                return PolicyViolation(
                    category=ViolationCategory.DESTRUCTIVE_COMMAND,
                    pattern=pattern,
                    severity="critical",
                    message=f"Blocked: {desc}"
                )
        
        # Check secret patterns (high)
        for pattern, desc in self.secret_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.warning(f"Secret exposure blocked: {desc}")
                return PolicyViolation(
                    category=ViolationCategory.SECRET_EXPOSURE,
                    pattern=pattern,
                    severity="high",
                    message=f"Blocked: {desc}"
                )
        
        # Check injection patterns (high)
        for pattern, desc in self.injection_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                # Allow legitimate code examples
                if self._is_likely_code_example(query):
                    continue
                logger.warning(f"Injection attempt blocked: {desc}")
                return PolicyViolation(
                    category=ViolationCategory.INJECTION_ATTEMPT,
                    pattern=pattern,
                    severity="high",
                    message=f"Blocked: {desc}"
                )
        
        # Check malicious patterns (high)
        for pattern, desc in self.malicious_patterns:
            if re.search(pattern, query_lower, re.IGNORECASE):
                logger.warning(f"Malicious code blocked: {desc}")
                return PolicyViolation(
                    category=ViolationCategory.MALICIOUS_CODE,
                    pattern=pattern,
                    severity="high",
                    message=f"Blocked: {desc}"
                )
        
        # Check sensitive paths (medium) - only block if combined with dangerous ops
        for pattern, desc in self.sensitive_paths:
            if re.search(pattern, query_lower, re.IGNORECASE):
                if self._has_dangerous_operation(query_lower):
                    logger.warning(f"Sensitive path operation blocked: {desc}")
                    return PolicyViolation(
                        category=ViolationCategory.SENSITIVE_PATH,
                        pattern=pattern,
                        severity="medium",
                        message=f"Blocked: {desc}"
                    )
        
        return None
    
    def _is_likely_code_example(self, query: str) -> bool:
        """Check if query is likely asking about code examples."""
        example_indicators = [
            "beispiel", "example", "wie funktioniert",
            "how does", "explain", "erkläre", "was macht",
            "what does", "syntax", "tutorial", "lernen",
            "learn", "documentation", "docs"
        ]
        query_lower = query.lower()
        return any(ind in query_lower for ind in example_indicators)
    
    def _has_dangerous_operation(self, query: str) -> bool:
        """Check if query contains dangerous operations."""
        dangerous_ops = [
            r'\bwrite\b', r'\bmodify\b', r'\bchange\b', r'\bedit\b',
            r'\bdelete\b', r'\bremove\b', r'\boverwrite\b',
            r'\b>\s*/', r'\bchmod\b', r'\bchown\b'
        ]
        return any(re.search(op, query, re.IGNORECASE) for op in dangerous_ops)
    
    def add_pattern(
        self,
        category: ViolationCategory,
        pattern: str,
        description: str
    ):
        """Add a custom pattern to the gate."""
        pattern_tuple = (pattern, description)
        
        if category == ViolationCategory.DESTRUCTIVE_COMMAND:
            self.destructive_patterns.append(pattern_tuple)
        elif category == ViolationCategory.SECRET_EXPOSURE:
            self.secret_patterns.append(pattern_tuple)
        elif category == ViolationCategory.INJECTION_ATTEMPT:
            self.injection_patterns.append(pattern_tuple)
        elif category == ViolationCategory.MALICIOUS_CODE:
            self.malicious_patterns.append(pattern_tuple)
        elif category == ViolationCategory.SENSITIVE_PATH:
            self.sensitive_paths.append(pattern_tuple)
    
    def get_stats(self) -> dict:
        """Get policy gate statistics."""
        return {
            "destructive_patterns": len(self.destructive_patterns),
            "secret_patterns": len(self.secret_patterns),
            "injection_patterns": len(self.injection_patterns),
            "malicious_patterns": len(self.malicious_patterns),
            "sensitive_path_patterns": len(self.sensitive_paths)
        }
