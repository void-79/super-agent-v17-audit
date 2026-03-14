"""
Smoke tests for all 6 improvements.
Run: python -m pytest test_all_improvements.py -v
Or:  python test_all_improvements.py
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from retry_backoff import ErrorCategory, RetryConfig, classify_error, retry_with_backoff
from smart_condenser import SmartContextCondenser
from stuck_detector import StuckDetector
from tool_truncator import ToolResultTruncator
from cost_tracker import CostTracker, TokenUsage
from edit_validator import EditValidator


# ── Test #1: Retry with Backoff ──

async def test_error_classification():
    assert classify_error(Exception("rate limit exceeded")) == ErrorCategory.TRANSIENT
    assert classify_error(Exception("context window exceeded")) == ErrorCategory.CONTEXT_OVERFLOW
    assert classify_error(Exception("unauthorized")) == ErrorCategory.AUTH
    assert classify_error(Exception("json decode error")) == ErrorCategory.MALFORMED
    assert classify_error(Exception("something unknown")) == ErrorCategory.FATAL
    assert classify_error(Exception("timeout error")) == ErrorCategory.TRANSIENT
    print("  ✅ #1a Error classification passed")


async def test_retry_backoff():
    config = RetryConfig(max_retries=2, base_delay=0.01)
    call_count = 0

    async def failing_then_ok():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("timeout error")
        return "success"

    result = await retry_with_backoff(failing_then_ok, config)
    assert result == "success"
    assert call_count == 3
    print("  ✅ #1b Retry with backoff passed")


# ── Test #2: Smart Condenser ──

async def test_smart_condenser():
    condenser = SmartContextCondenser(max_tokens=100, chars_per_token=1)

    messages = [
        {"role": "system", "content": "You are an agent."},
        {"role": "user", "content": "Do something"},
        {"role": "assistant", "content": "I'll use bash", "tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]},
        {"role": "tool", "content": "file1.py\nfile2.py"},
        {"role": "assistant", "content": "Here are the files"},
        {"role": "user", "content": "Now fix file1.py"},
    ]

    result = await condenser.condense(messages)
    assert len(result) < len(messages)
    assert result[0]["role"] == "system"
    assert "[CONDENSED HISTORY]" in result[1]["content"]
    assert result[-1]["content"] == "Now fix file1.py"
    print("  ✅ #2 Smart Context Condenser passed")


# ── Test #3: Stuck Detector ──

def test_stuck_detector():
    detector = StuckDetector(max_repeats=3)

    assert detector.is_stuck() is None

    for _ in range(3):
        detector.record_tool_call("bash", {"command": "ls"})
    assert "Repeated identical tool call" in detector.is_stuck()

    detector.reset()
    assert detector.is_stuck() is None

    detector.record_tool_call("read", {"path": "a.py"})
    detector.record_tool_call("write", {"path": "a.py", "content": "x"})
    detector.record_tool_call("read", {"path": "a.py"})
    detector.record_tool_call("write", {"path": "a.py", "content": "x"})
    assert "Alternating" in detector.is_stuck()

    detector.reset()
    for _ in range(3):
        detector.record_error()
    assert "Consecutive errors" in detector.is_stuck()

    print("  ✅ #3 Stuck Detector passed")


# ── Test #4: Tool Result Truncator ──

def test_tool_truncator():
    truncator = ToolResultTruncator(max_chars=500, head_lines=5, tail_lines=3)

    short = "hello world"
    assert truncator.truncate(short) == short

    long_result = "\n".join(f"line {i}" for i in range(200))
    truncated = truncator.truncate(long_result, "bash")
    assert "omitted" in truncated
    assert "line 0" in truncated
    assert "line 199" in truncated
    assert len(truncated) < len(long_result)

    print("  ✅ #4 Tool Result Truncator passed")


# ── Test #5: Cost Tracker ──

def test_cost_tracker():
    tracker = CostTracker(budget_limit=0.10)

    usage1 = tracker.record(prompt_tokens=1000, completion_tokens=500, model="gpt-4o", latency_ms=200)
    assert usage1.total_tokens == 1500
    assert usage1.estimated_cost > 0

    tracker.record(prompt_tokens=2000, completion_tokens=1000, model="gpt-4o", latency_ms=300)
    assert tracker.total_calls == 2
    assert tracker.total_tokens == 4500
    assert tracker.total_cost > 0

    tracker2 = CostTracker(budget_limit=0.001)
    tracker2.record(prompt_tokens=100000, completion_tokens=50000, model="gpt-4", latency_ms=200)
    assert tracker2.is_over_budget()

    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert "estimated_cost_usd" in summary

    print("  ✅ #5 Cost Tracker passed")


# ── Test #6: Edit Validator ──

def test_edit_validator():
    validator = EditValidator(similarity_threshold=0.8)

    content = 'def hello():\n    print("Hello, World!")\n    return True\n\ndef goodbye():\n    print("Goodbye!")\n'

    new_content, msg, ok = validator.apply_edit_with_validation(
        content,
        '    print("Hello, World!")',
        '    print("Hello, Universe!")',
        "test.py",
    )
    assert ok, f"Expected ok but got: {msg}"
    assert "Hello, Universe!" in new_content

    bad_content, bad_msg, bad_ok = validator.apply_edit_with_validation(
        'x = 1\ny = 2\n',
        'y = 2',
        'y = ((',
        "test.py",
    )
    assert not bad_ok
    assert "SyntaxError" in bad_msg

    html_content, html_msg, html_ok = validator.apply_edit_with_validation(
        '<div>hello</div>',
        'hello',
        'world',
        "test.html",
    )
    assert html_ok
    assert "world" in html_content

    print("  ✅ #6 Edit Validator passed")


# ── Run All ──

async def run_all():
    await test_error_classification()
    await test_retry_backoff()
    await test_smart_condenser()
    test_stuck_detector()
    test_tool_truncator()
    test_cost_tracker()
    test_edit_validator()
    print("\n  ✅ All 6 improvements validated!")


if __name__ == "__main__":
    asyncio.run(run_all())
