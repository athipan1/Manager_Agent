"""Workflow layer for Manager_Agent.

Workflows coordinate multiple services/clients but should avoid owning low-level
business helpers. Route handlers in app.main should delegate here over time.
"""
