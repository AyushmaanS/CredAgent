"""Local web UI for CredAgent (D-089): a small JSON API over the existing orchestrator, and a static frontend.

Nothing here changes the backend: the orchestrator runs unchanged on worker threads and talks to the person through
`WebIO` instead of the terminal.
"""
