"""
Improvement #4: Intelligent Tool Result Truncation

Inspired by: Aider (base_coder.py), Cline (context-window-utils.ts)
Addresses: Weakness #4 — no tool output truncation

Integration:
    In Agent.__init__():
        self.truncator = ToolResultTruncator(max_chars=20000)

    In Agent._execute_tools(), before recording the result event:
        result = self.truncator.truncate(result, tool_name)
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class ToolResultTruncator:
    """Intelligently truncate tool results to preserve useful content.

    Strategies:
    - Keep first N and last M lines (head+tail) for long output
    - Detect and preserve error messages with priority
    - Track cumulative tool output size for context budget
    """

    def __init__(
        self,
        max_chars: int = 20000,
        head_lines: int = 50,
        tail_lines: int = 30,
        error_priority: bool = True,
    ):
        """Initialize truncator.

        Args:
            max_chars: Maximum characters per tool result.
            head_lines: Number of lines to keep from the start.
            tail_lines: Number of lines to keep from the end.
            error_priority: If True, prioritize error-relevant lines.
        """
        self.max_chars = max_chars
        self.head_lines = head_lines
        self.tail_lines = tail_lines
        self.error_priority = error_priority
        self._total_chars_used: int = 0

    def truncate(self, result: str, tool_name: str = "") -> str:
        """Truncate a tool result while preserving important content.

        Args:
            result: Raw tool output.
            tool_name: Name of the tool (for context-aware truncation).

        Returns:
            Truncated result with indicator if truncation occurred.
        """
        if len(result) <= self.max_chars:
            self._total_chars_used += len(result)
            return result

        lines = result.split("\n")

        # If error output, prioritize error lines
        if self.error_priority:
            error_keywords = ("error", "exception", "traceback", "failed", "warning")
            error_lines = [
                l for l in lines
                if any(kw in l.lower() for kw in error_keywords)
            ]
            if error_lines and len(error_lines) < self.head_lines:
                error_section = "\n".join(error_lines)
                if len(error_section) <= self.max_chars:
                    header = f"[Truncated: {len(lines)} lines → {len(error_lines)} error-relevant lines]\n"
                    truncated = header + error_section
                    self._total_chars_used += len(truncated)
                    return truncated

        # Head + tail strategy
        if len(lines) > self.head_lines + self.tail_lines:
            head = lines[: self.head_lines]
            tail = lines[-self.tail_lines:]
            omitted = len(lines) - self.head_lines - self.tail_lines
            truncated_result = (
                "\n".join(head)
                + f"\n\n... [{omitted} lines omitted] ...\n\n"
                + "\n".join(tail)
            )
        else:
            # Just character-truncate
            truncated_result = (
                result[: self.max_chars]
                + f"\n... [truncated at {self.max_chars} chars]"
            )

        self._total_chars_used += len(truncated_result)
        return truncated_result

    @property
    def total_chars_used(self) -> int:
        """Total characters consumed by tool results this session."""
        return self._total_chars_used

    def reset_budget(self) -> None:
        """Reset the cumulative character counter."""
        self._total_chars_used = 0
