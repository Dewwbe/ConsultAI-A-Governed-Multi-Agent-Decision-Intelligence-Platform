"""Tests must be hermetic: never read backend/.env or call a real model."""
import os

# Environment variables take precedence over the .env file in pydantic-settings.
os.environ["LLM_PROVIDER"] = "stub"
os.environ["ENVIRONMENT"] = "dev"
