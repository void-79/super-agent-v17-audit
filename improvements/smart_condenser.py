"""
Improvement #2: LLM-Aware Context Condensation

Inspired by: Aider (aider/history.py ChatSummary)
Addresses: Weakness #2 — naive condensation loses reasoning

Drop-in replacement for ContextCondenser in core.py.

Integration:
    In Agent.__init__(), replace:
        self.condenser = ContextCondenser(max_tokens=config.max_context_tokens)
    With:
        self.condenser = SmartContextCondenser(max_tokens=config.max_context_tokens)
"""

import json
import logging
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class SummaryProvider(Protocol):
    """Protocol for generating summaries via LLM."""
    async def summarize(self, text: str, max_tokens: int) -> str: ...


class SmartContextCondenser:
    """Context condensation using structured extraction + optional LLM summarization.

    Unlike the current ContextCondenser which only lists tool names,
    this creates meaningful summaries preserving key decisions and outcomes.
    Falls back to extraction-based summary if no LLM is available.
    """

    def __init__(
        self,
        max_tokens: int = 120000,
        summary_provider: Optional[SummaryProvider] = None,
        chars_per_token: int = 4,
    ):
        self.max_tokens = max_tokens
        self.summary_provider = summary_provider
        self._chars_per_token = chars_per_token

    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count from messages."""
        total_chars = sum(
            len(str(m.get("content", ""))) + len(json.dumps(m.get("tool_calls", [])))
            for m in messages
        )
        return total_chars // self._chars_per_token

    async def condense(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Condense messages if approaching token limit.

        Strategy:
        1. Keep system prompt (first message) intact
        2. Keep last 2 messages intact (recent context)
        3. Summarize middle messages preserving:
           - Tool calls and their outcomes
           - Key decisions and reasoning
           - Error patterns encountered
        """
        estimated = self.estimate_tokens(messages)

        if estimated < self.max_tokens * 0.8:
            return messages

        if len(messages) < 4:
            return messages

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        start_idx = 1 if system_msg else 0
        middle = messages[start_idx:-2]
        tail = messages[-2:]

        summary_content = await self._create_smart_summary(middle)

        condensed: List[Dict[str, Any]] = []
        if system_msg:
            condensed.append(system_msg)
        condensed.append({
            "role": "system",
            "content": f"[CONDENSED HISTORY]\n{summary_content}",
        })
        condensed.extend(tail)

        return condensed

    async def _create_smart_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Create an intelligent summary of conversation history."""
        tool_calls: List[str] = []
        tool_results: List[str] = []
        errors: List[str] = []
        decisions: List[str] = []

        for msg in messages:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))

            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    name = tc.get("name", "unknown")
                    args = tc.get("arguments", {})
                    if isinstance(args, dict):
                        args_summary = ", ".join(
                            f"{k}={str(v)[:50]}" for k, v in list(args.items())[:3]
                        )
                    else:
                        args_summary = str(args)[:100]
                    tool_calls.append(f"{name}({args_summary})")

            if role == "tool":
                result_preview = content[:200]
                if content.startswith("ERROR"):
                    errors.append(result_preview)
                else:
                    tool_results.append(result_preview)

            if role == "assistant" and content and not msg.get("tool_calls"):
                first_line = content.split("\n")[0][:150]
                decisions.append(first_line)

        parts: List[str] = []
        if tool_calls:
            unique_tools = list(dict.fromkeys(tool_calls))
            parts.append(f"Actions taken ({len(tool_calls)} total): {'; '.join(unique_tools[:15])}")
        if errors:
            parts.append(f"Errors encountered ({len(errors)}): {'; '.join(errors[:5])}")
        if decisions:
            parts.append(f"Key decisions: {'; '.join(decisions[:5])}")
        if tool_results:
            parts.append(f"Successful results: {len(tool_results)} tool executions")

        summary = "\n".join(parts) if parts else "Previous context condensed (no significant actions)."

        if self.summary_provider:
            try:
                raw_text = "\n".join(
                    f"[{m.get('role', '?')}] {str(m.get('content', ''))[:300]}"
                    for m in messages
                )
                llm_summary = await self.summary_provider.summarize(raw_text, 500)
                if llm_summary:
                    summary = llm_summary
            except Exception as e:
                logger.warning(f"LLM summary failed, using extraction: {e}")

        return summary
