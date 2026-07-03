from celery import shared_task

from .ai_service import generate_summary
from .models import Report, ReportSummary


@shared_task
def generate_report_summary(report_id):
    report = Report.objects.select_related("mineral", "region").get(id=report_id)

    pdf_text = ""
    if report.pdf_file:
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(report.pdf_file.path)
            pages = [page.extract_text() or "" for page in reader.pages[:10]]
            pdf_text = "\n".join(pages)[:4000]
        except Exception:
            pdf_text = ""

    context = (
        f"Report: {report.title}\n"
        f"Mineral: {report.mineral.name}\n"
        f"Region: {report.region.name if report.region else 'Tanzania'}\n"
        f"Description: {report.description}\n"
        f"PDF excerpt: {pdf_text}\n"
    )

    summary_text, model_used = generate_summary(context)
    key_findings = _extract_findings(summary_text)

    ReportSummary.objects.update_or_create(
        report=report,
        defaults={
            "summary": summary_text,
            "key_findings": key_findings,
            "model_used": model_used,
        },
    )

    report.refresh_from_db()
    if not report.pdf_file:
        from .pdf_service import ensure_report_pdf

        ensure_report_pdf(report)


def _extract_findings(summary_text: str) -> list[str]:
    for marker in ("Key findings:", "key findings:", "KEY FINDINGS:"):
        if marker in summary_text:
            _, tail = summary_text.split(marker, 1)
            findings = []
            for line in tail.split("\n"):
                stripped = line.strip()
                if not stripped:
                    if findings:
                        break
                    continue
                if stripped.startswith(("-", "•")):
                    findings.append(stripped.lstrip("- •").strip())
                elif findings:
                    break
            return [f for f in findings if f][:8]

    lines = [
        line.strip("- •")
        for line in summary_text.split("\n")
        if line.strip().startswith(("-", "•"))
    ]
    return [line for line in lines if line][:8]
