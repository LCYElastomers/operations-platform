"""Platform-wide Notifications and Email Management.

Business modules publish events into the caller's PostgreSQL transaction; a
worker claims outbox rows and delivers through a provider adapter (Resend).
Modules never import Resend or call the provider directly.
"""
