"""
Improvement #5: Token & Cost Tracking with Budget Enforcement

Inspired by: Aider (aider/models.py), Cline (ModelContextTracker)
Addresses: Weakness #5 — no cost estimation or budget enforcement

Integration:
    In Agent.__init__():
        self.cost_tracker = CostTracker(budget_limit=config.budget_limit)

    In Agent._get_llm_response(), after successful response:
        self.cost_tracker.record(
            prompt_tokens=response.usage["prompt_tokens"],
            completion_tokens=response.usage["completion_tokens"],
            model=response.model,
            latency_ms=response.latency_ms,
        )
        if self.cost_tracker.is_over_budget():
            raise BudgetExceededError(self.cost_tracker.summary())

    Add to AgentConfig:
        budget_limit: Optional[float] = None  # USD limit
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Tracks token usage and estimated cost for a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    latency_ms: float = 0.0
    estimated_cost: float = 0.0


class CostTracker:
    """Tracks cumulative token usage and cost across an agent session.

    Provides per-call and aggregate statistics, budget enforcement,
    and per-model cost estimation.
    """

    # Approximate costs per 1M tokens (input, output)
    MODEL_COSTS: Dict[str, tuple] = {
        "gpt-4": (30.0, 60.0),
        "gpt-4o": (2.5, 10.0),
        "gpt-4o-mini": (0.15, 0.6),
        "gpt-4-turbo": (10.0, 30.0),
        "gpt-4.1": (2.0, 8.0),
        "gpt-4.1-mini": (0.4, 1.6),
        "o3-mini": (1.1, 4.4),
        "claude-3-opus": (15.0, 75.0),
        "claude-3-5-sonnet": (3.0, 15.0),
        "claude-sonnet-4": (3.0, 15.0),
        "claude-3-haiku": (0.25, 1.25),
        "claude-haiku-4": (0.8, 4.0),
        "deepseek-chat": (0.14, 0.28),
        "deepseek-reasoner": (0.55, 2.19),
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.15, 0.6),
        "qwen-max": (1.6, 6.4),
    }

    def __init__(self, budget_limit: Optional[float] = None):
        """Initialize cost tracker.

        Args:
            budget_limit: Maximum allowed spend in USD. None = no limit.
        """
        self._calls: List[TokenUsage] = []
        self.budget_limit = budget_limit

    def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str,
        latency_ms: float = 0.0,
    ) -> TokenUsage:
        """Record a single LLM call's usage.

        Args:
            prompt_tokens: Input token count.
            completion_tokens: Output token count.
            model: Model identifier.
            latency_ms: Call latency.

        Returns:
            TokenUsage with estimated cost.
        """
        cost = self._estimate_cost(prompt_tokens, completion_tokens, model)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model,
            latency_ms=latency_ms,
            estimated_cost=cost,
        )
        self._calls.append(usage)
        return usage

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        """Estimate cost based on model pricing."""
        model_lower = model.lower()
        for key, (input_cost, output_cost) in self.MODEL_COSTS.items():
            if key in model_lower:
                return (
                    (prompt_tokens / 1_000_000) * input_cost
                    + (completion_tokens / 1_000_000) * output_cost
                )
        # Default estimate for unknown models
        return (prompt_tokens + completion_tokens) / 1_000_000 * 5.0

    @property
    def total_tokens(self) -> int:
        """Total tokens across all calls."""
        return sum(u.total_tokens for u in self._calls)

    @property
    def total_cost(self) -> float:
        """Total estimated cost in USD."""
        return sum(u.estimated_cost for u in self._calls)

    @property
    def total_calls(self) -> int:
        """Number of LLM calls made."""
        return len(self._calls)

    @property
    def avg_latency_ms(self) -> float:
        """Average call latency."""
        if not self._calls:
            return 0.0
        return sum(u.latency_ms for u in self._calls) / len(self._calls)

    def is_over_budget(self) -> bool:
        """Check if spending has exceeded the budget."""
        if self.budget_limit is None:
            return False
        return self.total_cost > self.budget_limit

    def summary(self) -> Dict[str, Any]:
        """Get a summary of usage statistics."""
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "prompt_tokens": sum(u.prompt_tokens for u in self._calls),
            "completion_tokens": sum(u.completion_tokens for u in self._calls),
            "estimated_cost_usd": round(self.total_cost, 6),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "budget_limit_usd": self.budget_limit,
            "over_budget": self.is_over_budget(),
        }
