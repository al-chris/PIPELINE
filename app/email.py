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


def render_email_template(*, template_name: str, context: dict[str, Any]) -> str:
    """Renders an email template with the given context.
    This function takes a template name and a context dictionary, reads the template file,
    and returns the rendered HTML content using Jinja2 templating.
    Args:
        template_name (str): Name of the template file to render
        context (dict[str, Any]): Dictionary containing variables to be passed to the template
    Returns:
        str: Rendered HTML content of the email template
    Raises:
        FileNotFoundError: If the template file doesn't exist
        jinja2.exceptions.TemplateError: If there are errors in template syntax or rendering
    """

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
    """Send an email using SMTP settings from configuration.
    This asynchronous function sends an email using the emails library and configured SMTP settings.
    It supports both TLS and SSL connections and includes optional SMTP authentication.
    Args:
        email_to (str): Recipient's email address
        subject (str, optional): Email subject line. Defaults to empty string.
        html_content (str, optional): HTML content of the email. Defaults to empty string.
    Returns:
        None
    Raises:
        Exception: If there's an error during SMTP connection or sending the email
    Example:
        >>> await send_email(
        ...     email_to="recipient@example.com",
        ...     subject="Test email",
        ...     html_content="<h1>Hello World!</h1>"
        ... )
    """
    
    try:
        message = emails.Message(
            subject=subject,
            html=html_content,
            mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
        )
        smtp_options: dict[str, Any] = {
            "host": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "debug": False  # Add this to get detailed SMTP communication logs
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
    """
    Generate email reminder data with customized content.
    This function creates an email data object containing a subject line and HTML content
    for a reminder email. It uses project settings and a template to format the email.
    Args:
        email_to (str): Recipient email address.
        link (str): URL link to be included in the email content.
    Returns:
        EmailData: An object containing the formatted HTML content and subject line for the email.
    Example:
        email_data = generate_reminder_email("user@example.com", "http://localhost:8000/results/66a3183c-969c-47c8-9039-26892c6bd911")
    """

    project_name = settings.PROJECT_NAME
    subject = f"{project_name} - Reminder"
    html_content = render_email_template(
        template_name="notification.html",
        context={"project_name": settings.PROJECT_NAME, "link": link, "email": email_to},
    )
    return EmailData(html_content=html_content, subject=subject)