"""
Improvement #6: Edit Validation with Fuzzy Matching

Inspired by: Aider (aider/coders/editblock_coder.py)
Addresses: Weakness #6 — exact-match-only edits

Integration:
    In EditTool.execute(), replace the str.replace() logic with:

    validator = EditValidator()
    new_content, message, success = validator.apply_edit_with_validation(
        content, old_text, new_text, path
    )
    if success:
        with open(resolved_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    return message
"""

import ast
import difflib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EditValidator:
    """Validates and improves file edit operations.

    Enhancements over the base EditTool:
    1. Fuzzy matching when exact match fails
    2. Whitespace-normalized comparison
    3. Multi-occurrence disambiguation
    4. Post-edit syntax validation (for Python files)
    """

    def __init__(self, similarity_threshold: float = 0.85):
        """Initialize validator.

        Args:
            similarity_threshold: Minimum similarity score (0-1) for fuzzy matches.
        """
        self.similarity_threshold = similarity_threshold

    def find_best_match(
        self,
        content: str,
        search_text: str,
    ) -> Optional[tuple]:
        """Find the best match for search_text in content.

        Tries in order:
        1. Exact match (fast path)
        2. Whitespace-normalized match
        3. Fuzzy match via SequenceMatcher

        Returns:
            Tuple of (matched_text, start_idx, similarity_score) or None.
        """
        # 1. Exact match
        idx = content.find(search_text)
        if idx != -1:
            return (search_text, idx, 1.0)

        # 2. Whitespace-normalized match
        normalized_search = self._normalize_whitespace(search_text)
        lines = content.split("\n")
        search_lines = search_text.split("\n")
        search_len = len(search_lines)

        best_match = None
        best_score = 0.0

        for i in range(len(lines) - search_len + 1):
            candidate = "\n".join(lines[i : i + search_len])
            normalized_candidate = self._normalize_whitespace(candidate)

            if normalized_candidate == normalized_search:
                start = content.find(candidate)
                return (candidate, start, 0.99)

            # 3. Fuzzy match
            score = difflib.SequenceMatcher(
                None, normalized_search, normalized_candidate
            ).ratio()

            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                start = content.find(candidate)
                best_match = (candidate, start, score)

        return best_match

    def validate_python_syntax(self, content: str) -> Optional[str]:
        """Check if content is valid Python.

        Returns:
            Error message if invalid, None if valid.
        """
        try:
            ast.parse(content)
            return None
        except SyntaxError as e:
            return f"SyntaxError at line {e.lineno}: {e.msg}"

    def apply_edit_with_validation(
        self,
        file_content: str,
        old_text: str,
        new_text: str,
        file_path: str = "",
    ) -> tuple:
        """Apply an edit with fuzzy matching and syntax validation.

        Args:
            file_content: Current file content.
            old_text: Text to find and replace.
            new_text: Replacement text.
            file_path: File path (used for language-specific validation).

        Returns:
            Tuple of (new_content, status_message, success_bool).
        """
        match = self.find_best_match(file_content, old_text)

        if not match:
            suggestion = ""
            try:
                candidates = [
                    file_content[i:i+len(old_text)]
                    for i in range(0, max(1, len(file_content) - len(old_text)), 50)
                ]
                similar = difflib.get_close_matches(
                    old_text[:200], candidates, n=1, cutoff=0.5
                )
                if similar:
                    suggestion = f"\nDid you mean:\n{similar[0][:200]}..."
            except Exception:
                pass
            return (file_content, f"ERROR: Text not found in file.{suggestion}", False)

        matched_text, start_idx, score = match

        if score < 1.0:
            status_prefix = f"Fuzzy match (score={score:.2f}): "
        else:
            status_prefix = ""

        # Apply the replacement
        new_content = (
            file_content[:start_idx]
            + new_text
            + file_content[start_idx + len(matched_text):]
        )

        # Validate syntax for Python files
        if file_path.endswith(".py"):
            syntax_error = self.validate_python_syntax(new_content)
            if syntax_error:
                return (
                    file_content,
                    f"{status_prefix}Edit would introduce syntax error: {syntax_error}",
                    False,
                )

        return (
            new_content,
            f"{status_prefix}Successfully edited. Replaced {len(matched_text)} chars with {len(new_text)} chars.",
            True,
        )

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        """Normalize whitespace for comparison."""
        lines = text.split("\n")
        return "\n".join(line.rstrip() for line in lines)
