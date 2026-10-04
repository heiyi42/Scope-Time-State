"""
LLM provider protocol for the STS pipeline.

This module defines the abstract interface that all LLM providers must implement.
"""

from typing import Protocol


class LLMProvider(Protocol):
    """
    Protocol for LLM providers used in text generation.

    All concrete LLM providers implement this interface so extraction,
    construction, and generation share one narrow dependency boundary.
    """

    async def generate(self, prompt: str, temperature: float | None = None, extra_body: dict | None = None, response_format: dict | None = None) -> str:
        """
        Generate a response for the given prompt.

        Args:
            prompt: Input prompt text
            temperature: Optional temperature override for this request

        Returns:
            Generated response text

        Raises:
            Exception: If generation fails
        """
        ...

    async def test_connection(self) -> bool:
        """
        Test the connection to the LLM provider.

        Returns:
            True if connection successful, False otherwise
        """
        ...

    def __repr__(self) -> str:
        """String representation of the provider."""
        ...


class LLMError(Exception):
    """Exception raised for LLM-related errors."""
    pass
