"""Outgoing email over SMTP (standard library only).

A message counts as sent only when the mail server accepted it. Errors are
reported to the caller with the server's reply and never include credentials.
"""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import Settings


@dataclass(frozen=True)
class OutgoingMail:
    to_email: str
    to_name: str | None
    subject: str
    body: str


class MailNotConfiguredError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    """The server refused the message or could not be reached. Nothing was sent."""


def _message(settings: Settings, mail: OutgoingMail) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.smtp_from or ""
    message["To"] = formataddr((mail.to_name or "", mail.to_email))
    message["Subject"] = mail.subject
    message["Message-ID"] = make_msgid(domain=(settings.smtp_from or "").rpartition("@")[2] or None)
    message.set_content(mail.body)
    return message


def send(settings: Settings, mail: OutgoingMail) -> None:
    """Send one message, or raise. Returns only once the server accepted it."""
    if not settings.mail_enabled or settings.smtp_host is None:
        raise MailNotConfiguredError("Outgoing email is not configured.")
    message = _message(settings, mail)
    context = ssl.create_default_context()
    timeout = settings.smtp_timeout_seconds
    try:
        if settings.smtp_security == "tls":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=timeout, context=context
            )
        else:
            client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
        with client:
            if settings.smtp_security == "starttls":
                client.starttls(context=context)
            if settings.smtp_username and settings.smtp_password is not None:
                client.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            refused = client.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise MailDeliveryError("The mail server refused the sign-in.") from None
    except smtplib.SMTPRecipientsRefused:
        raise MailDeliveryError("The mail server refused the recipient address.") from None
    except smtplib.SMTPResponseException as error:
        raise MailDeliveryError(f"The mail server replied {error.smtp_code}.") from None
    except (smtplib.SMTPException, OSError) as error:
        raise MailDeliveryError(
            f"The mail server could not be reached ({type(error).__name__})."
        ) from None
    if refused:
        raise MailDeliveryError("The mail server refused the recipient address.")
