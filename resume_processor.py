import io
import logging
import os

import anthropic
from docx import Document
from pypdf import PdfReader

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

ALLOWED_EXTENSIONS = ("pdf", "docx")

SUMMARY_SYSTEM_PROMPT = """You are an HR assistant for a building maintenance
service. Given the raw text extracted from a technician's resume, write a
short professional summary of their skills and experience for use by a
ticket-routing system when matching technicians to maintenance requests.

Respond with 3-5 sentences of plain text only - no markdown, no headings,
no bullet points, no preamble. Write in the same language as the resume
text. Focus on trade skills, years of experience, certifications, and
specialties relevant to building maintenance (plumbing, electrical,
carpentry, general repairs, etc.)."""


class ResumeProcessingError(Exception):
    """User-facing error: unsupported file type or no extractable text."""


def allowed_filename(filename):
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS


def extract_text(filename, file_bytes):
    """Extract raw text from a PDF or DOCX resume.

    Raises ResumeProcessingError (safe to show to the user) if the file
    extension isn't supported or no text could be extracted (e.g. a
    scanned image with no text layer).
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        text = _extract_pdf_text(file_bytes)
    elif ext == "docx":
        text = _extract_docx_text(file_bytes)
    else:
        raise ResumeProcessingError("Підтримуються лише файли у форматі PDF або DOCX.")

    text = (text or "").strip()
    if not text:
        raise ResumeProcessingError(
            "Не вдалося витягнути текст із файлу. Переконайтесь, що це "
            "текстовий документ, а не скановане зображення."
        )
    return text


def _extract_pdf_text(file_bytes):
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise ResumeProcessingError(
            "Не вдалося прочитати PDF-файл. Перевірте, що файл не пошкоджений."
        ) from exc


def _extract_docx_text(file_bytes):
    try:
        document = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in document.paragraphs)
    except Exception as exc:
        raise ResumeProcessingError(
            "Не вдалося прочитати DOCX-файл. Перевірте, що файл не пошкоджений."
        ) from exc


def generate_summary(resume_text):
    """Generate a short professional summary of a resume via Claude.

    Raises RuntimeError on any failure (missing API key, API error, empty
    response) - callers are expected to catch it and show a generic
    "try again later" message, without saving anything.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=SUMMARY_SYSTEM_PROMPT,
            # Keep the prompt within a sane size regardless of resume length.
            messages=[{"role": "user", "content": resume_text[:12000]}],
        )
    except Exception as exc:
        logger.exception("Claude API call failed while summarizing a resume")
        raise RuntimeError("Claude API call failed") from exc

    text = next((block.text for block in response.content if block.type == "text"), "")
    text = text.strip()
    if not text:
        raise RuntimeError("Claude returned an empty summary")
    return text
