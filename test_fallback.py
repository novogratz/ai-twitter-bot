#!/usr/bin/env python3
"""Test script to verify fallback mechanism works correctly."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from llm_client import run_llm, _should_fallback, LLMResult

def test_fallback_logic():
    """Test the fallback logic directly."""
    print("Testing fallback logic...")
    
    # Test case 1: Normal success case (should not fallback)
    success_result = LLMResult(0, "Test output", "")
    should_fallback = _should_fallback(success_result)
    print(f"Success result should fallback: {should_fallback}")
    
    # Test case 2: Failed command (should fallback)
    failed_result = LLMResult(1, "", "Error occurred")
    should_fallback = _should_fallback(failed_result)
    print(f"Failed result should fallback: {should_fallback}")
    
    # Test case 3: Empty output (should fallback)
    empty_result = LLMResult(0, "", "")
    should_fallback = _should_fallback(empty_result)
    print(f"Empty result should fallback: {should_fallback}")
    
    # Test case 4: Rate limit error (should fallback)
    rate_limit_result = LLMResult(75, "", "Rate limit exceeded")
    should_fallback = _should_fallback(rate_limit_result)
    print(f"Rate limit result should fallback: {should_fallback}")

if __name__ == "__main__":
    test_fallback_logic()