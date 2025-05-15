# type: ignore

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import emails
from jinja2 import Template

from app.config import settings

from app.logging import logger


@dataclass
class EmailData:
    html_content: str
    subject: str


async def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    template_str = (
        Path(__file__).parent / "templates" / "emails" / "build" / template_name
    ).read_text()
    html_content = Template(template_str).render(context)
    return html_content


async def send_email(
    *,
    email_to: str,
    subject: str = "",
    html_content: str = "",
) -> None:
    assert settings.emails_enabled, "no provided configuration for email variables"
    try:
        message = emails.Message(
            subject=subject,
            html=html_content,
            mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
        )
        smtp_options: dict[str, Any] = {
            "host": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "debug": True  # Add this to get detailed SMTP communication logs
        }
        if settings.SMTP_TLS:
            smtp_options["tls"] = True
        elif settings.SMTP_SSL:
            smtp_options["ssl"] = True
        if settings.SMTP_USER:
            smtp_options["user"] = settings.SMTP_USER
        if settings.SMTP_PASSWORD:
            smtp_options["password"] = settings.SMTP_PASSWORD
            
        try:
            response = message.send(to=email_to, smtp=smtp_options)
            logger.info(f"Raw SMTP response: {response}")
            logger.info(f"SMTP response status code: {response.status_code}")
            logger.info(f"SMTP response status text: {response.status_text}")
            logger.info(f"SMTP response error: {getattr(response, 'error', None)}")
        except Exception as smtp_err:
            logger.error(f"SMTP error during send: {str(smtp_err)}")
            raise
            
    except Exception as e:
        logger.error(f"Error in send_email: {str(e)}")
        raise


def generate_reminder_email(email_to: str, link: str) -> EmailData:
    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Reminder"
    html_content = await render_email_template(
        template_name="reminder.html",
        context={"project_name": settings.PROJECT_NAME, "link": link, "email": email_to},
    )
    return EmailData(html_content=html_content, subject=subject)