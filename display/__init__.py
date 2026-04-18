"""Pygame kiosk client for PiClock.

Replaces the Chromium browser frontend on memory-constrained hardware
(Pi Zero 2 W). Talks to the FastAPI backend over HTTP/SSE and renders
clock, weather, forecast, and animated radar directly with pygame.

Run with: ``uv run python -m display``
"""
