"""
Rapports PDF (ReportLab, sans dépendance système) : en-tête de l'entreprise, titre, période,
tableau, pied de page numéroté. Les montants arrivent déjà mis en forme (texte).
"""
import io

from django.utils.translation import gettext
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BLUE = colors.HexColor("#1F4E79")
GREY = colors.HexColor("#F2F4F7")


def _clean(text):
    """Espaces fines insécables (séparateur de milliers) → espaces simples, que toutes les polices ont."""
    return str(text if text is not None else "").replace(" ", " ").replace("\xa0", " ")


def table_report(*, company, title, subtitle, headers, rows, totals=None, notes=(), numeric_from=1, widths=None,
                 orientation="landscape", generated="", sections=()):
    """
    `rows` : listes de cellules (texte). Les colonnes à partir de `numeric_from` sont alignées à droite.
    Retourne le contenu du PDF (bytes).
    """
    buffer = io.BytesIO()
    pagesize = landscape(A4) if orientation == "landscape" else A4
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=_clean(title), author=_clean(company))
    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    cell_bold = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    cell_right = ParagraphStyle("cellr", parent=cell, alignment=2)
    cell_bold_right = ParagraphStyle("cellbr", parent=cell_bold, alignment=2)

    def line(values, bold=False):
        return [Paragraph(_escape(value), (cell_bold_right if bold else cell_right) if index >= numeric_from
                          else (cell_bold if bold else cell)) for index, value in enumerate(values)]

    story = [
        Paragraph(f"<b>{_escape(company)}</b>", ParagraphStyle("co", parent=styles["Normal"], fontSize=9, textColor=colors.grey)),
        Spacer(1, 2 * mm),
        Paragraph(_escape(title), ParagraphStyle("t", parent=styles["Title"], fontSize=15, alignment=0, spaceAfter=2)),
        Paragraph(_escape(subtitle), ParagraphStyle("s", parent=styles["Normal"], fontSize=9, textColor=colors.grey)),
        Spacer(1, 5 * mm),
    ]
    data = [line(headers, bold=True)]
    data += [line(row) for row in rows]
    if totals:
        data.append(line(totals, bold=True))
    available = pagesize[0] - doc.leftMargin - doc.rightMargin
    if widths:
        scale = available / sum(widths)
        col_widths = [w * scale for w in widths]
    else:
        col_widths = [available / len(headers)] * len(headers)
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), GREY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1 if not totals else -2), [colors.white, colors.HexColor("#FAFBFC")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if totals:
        style += [("BACKGROUND", (0, -1), (-1, -1), GREY), ("LINEABOVE", (0, -1), (-1, -1), 0.8, BLUE)]
    table.setStyle(TableStyle(style))
    story.append(table)
    for section_title, section_headers, section_rows, section_widths, section_numeric in sections:
        story += [Spacer(1, 6 * mm), Paragraph(f"<b>{_escape(section_title)}</b>", styles["Heading3"])]
        numeric_from = section_numeric
        section = [line(section_headers, bold=True)] + [line(row) for row in section_rows]
        scale = available / sum(section_widths)
        extra = Table(section, colWidths=[w * scale for w in section_widths], repeatRows=1)
        extra.setStyle(TableStyle([item for item in style if item[0] != "BACKGROUND" or item[1] == (0, 0)]))
        story.append(extra)
    for note in notes:
        story += [Spacer(1, 3 * mm), Paragraph(_escape(note), ParagraphStyle("n", parent=styles["Normal"], fontSize=7.5, textColor=colors.grey))]

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(doc.leftMargin, 8 * mm, _clean(f"EasyMaint · {company} · {generated}"))
        canvas.drawRightString(pagesize[0] - doc.rightMargin, 8 * mm, gettext("Page %(n)s") % {"n": document.page})
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _escape(text):
    return _clean(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def document(*, company, title, reference="", subtitle="", sections=(), signatures=(), generated="", orientation="portrait"):
    """
    Fiche structurée (fiche d'intervention, fiche équipement, rapport) : en-tête, puis sections.
    Section : {"title": ..., "kv": [(libellé, valeur)], "text": "...", "lines": n (lignes vides à remplir),
               "table": (en-têtes, lignes, largeurs, première colonne numérique)}.
    `signatures` : libellés des cases de signature en bas de document.
    """
    buffer = io.BytesIO()
    pagesize = landscape(A4) if orientation == "landscape" else A4
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=16 * mm, title=_clean(f"{title} {reference}"), author=_clean(company))
    available = pagesize[0] - doc.leftMargin - doc.rightMargin
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, leading=11)
    bold = ParagraphStyle("bold", parent=small, fontName="Helvetica-Bold")
    right = ParagraphStyle("right", parent=small, alignment=2)
    head = ParagraphStyle("head", parent=styles["Heading3"], fontSize=10.5, textColor=BLUE, spaceBefore=8, spaceAfter=4)
    header = Table([[
        Paragraph(f"<b>{_escape(company)}</b><br/>{_escape(subtitle)}", small),
        Paragraph(f"<font size=13><b>{_escape(title)}</b></font><br/><font size=10>{_escape(reference)}</font>",
                  ParagraphStyle("t", parent=small, alignment=2, leading=16)),
    ]], colWidths=[available * 0.5, available * 0.5])
    header.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1, BLUE), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story = [header, Spacer(1, 3 * mm)]
    grid = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for section in sections:
        if section.get("title"):
            story.append(Paragraph(_escape(section["title"]), head))
        if section.get("kv"):
            pairs = list(section["kv"])
            rows = []
            for index in range(0, len(pairs), 2):
                row = []
                for label, value in pairs[index:index + 2]:
                    row += [Paragraph(_escape(label), bold), Paragraph(_escape(value).replace("\n", "<br/>"), small)]
                while len(row) < 4:
                    row.append("")
                rows.append(row)
            table = Table(rows, colWidths=[available * w for w in (0.17, 0.33, 0.17, 0.33)])
            table.setStyle(TableStyle(grid + [("BACKGROUND", (0, 0), (0, -1), GREY), ("BACKGROUND", (2, 0), (2, -1), GREY)]))
            story.append(table)
        if section.get("text") is not None:
            text = _escape(section["text"] or "—").replace("\n", "<br/>")
            box = Table([[Paragraph(text, small)]], colWidths=[available])
            box.setStyle(TableStyle(grid))
            story.append(box)
        if section.get("lines"):
            box = Table([[""] for _i in range(section["lines"])], colWidths=[available], rowHeights=[7 * mm] * section["lines"])
            box.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#98A2B3")),
                                     ("BOX", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D5DD"))]))
            story.append(box)
        if section.get("table"):
            headers, rows, widths, numeric_from = section["table"]
            if not rows:
                story.append(Paragraph("—", small))
            else:
                def line(values, is_header=False):
                    return [Paragraph(_escape(v), bold if is_header else (right if i >= numeric_from else small))
                            for i, v in enumerate(values)]
                data = [line(headers, True)] + [line(r) for r in rows]
                scale = available / sum(widths)
                table = Table(data, colWidths=[w * scale for w in widths], repeatRows=1)
                table.setStyle(TableStyle(grid + [("BACKGROUND", (0, 0), (-1, 0), GREY)]))
                story.append(table)
    if signatures:
        story.append(Spacer(1, 6 * mm))
        width = available / len(signatures)
        name, day, sign = _escape(gettext("Nom :")), _escape(gettext("Date :")), _escape(gettext("Signature :"))
        cells = [[Paragraph(f"<b>{_escape(label)}</b><br/>{name}<br/><br/>{day}<br/><br/>{sign}", small) for label in signatures]]
        table = Table(cells, colWidths=[width] * len(signatures), rowHeights=[34 * mm])
        table.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#98A2B3")),
                                   ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#98A2B3")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(table)

    def footer(canvas, document_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(doc.leftMargin, 8 * mm, _clean(f"EasyMaint · {company} · {generated}"))
        canvas.drawRightString(pagesize[0] - doc.rightMargin, 8 * mm, f"{_clean(reference)} · " + gettext("page %(n)s") % {"n": document_.page})
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
