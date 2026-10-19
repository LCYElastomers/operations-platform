"""Email delivery provider adapters. Only ``resend`` talks to Resend."""

from app.notifications.providers.base import EmailMessage, EmailProvider, ProviderSendResult

__all__ = ["EmailMessage", "EmailProvider", "ProviderSendResult"]
