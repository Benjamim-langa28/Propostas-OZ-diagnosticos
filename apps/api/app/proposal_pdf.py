from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GREEN = colors.HexColor("#175f4d")
MUTED = colors.HexColor("#67756d")
LIGHT = colors.HexColor("#eef4ee")
LINE = colors.HexColor("#dce4dc")


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", " ") + " EUR"


def build_proposal_pdf(request: dict, proposal: dict, items: list[dict]) -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Proposta {proposal['proposal_no']}", author="OZ Diagnóstico e Engenharia",
    )
    base = getSampleStyleSheet()
    styles = {
        "brand": ParagraphStyle("OZBrand", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=18,
                                leading=21, textColor=GREEN, spaceAfter=2),
        "subbrand": ParagraphStyle("OZSubBrand", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8,
                                   leading=11, textColor=MUTED, tracking=1.2),
        "ref": ParagraphStyle("OZRef", parent=base["Normal"], fontSize=9, leading=14, textColor=MUTED,
                              alignment=TA_RIGHT),
        "title": ParagraphStyle("OZTitle", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=18,
                                leading=23, textColor=colors.HexColor("#24352b"), spaceBefore=12, spaceAfter=13),
        "body": ParagraphStyle("OZBody", parent=base["BodyText"], fontName="Helvetica", fontSize=9,
                               leading=14, textColor=colors.HexColor("#435148"), spaceAfter=7),
        "section": ParagraphStyle("OZSection", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11,
                                  leading=15, textColor=GREEN, spaceBefore=13, spaceAfter=7),
        "small": ParagraphStyle("OZSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=8,
                                leading=12, textColor=MUTED),
    }
    fields = request.get("extracted_fields") or {}
    client = escape(str(fields.get("client_name") or "Cliente"))
    project = escape(str(fields.get("project_name") or request.get("title") or "Projeto"))
    location = escape(str(fields.get("location") or ""))
    reference = escape(str(proposal["proposal_no"]))

    story = []
    masthead = Table([
        [Paragraph("OZ", styles["brand"]), Paragraph(
            f"PROPOSTA DE SERVIÇOS<br/><b>{reference}</b><br/>{date.today().strftime('%d/%m/%Y')}", styles["ref"]
        )],
        [Paragraph("DIAGNÓSTICO E ENGENHARIA", styles["subbrand"]), ""],
    ], colWidths=[90 * mm, 80 * mm])
    masthead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("SPAN", (0, 0), (0, 1)), ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ("LINEBELOW", (0, 1), (-1, 1), 1, GREEN),
    ]))
    story.extend([masthead, Spacer(1, 9 * mm), Paragraph(project, styles["title"])])
    story.append(Paragraph(f"Exmo.(a) Senhor(a) {client},", styles["body"]))
    intro = "Apresentamos a proposta para os serviços de diagnóstico e engenharia relativos ao pedido recebido."
    story.append(Paragraph(intro, styles["body"]))
    if location:
        story.append(Paragraph(f"Local da intervenção: {location}", styles["body"]))

    story.append(Paragraph("Âmbito e honorários", styles["section"]))
    table_data = [["SERVIÇO", "QTD.", "PREÇO UNITÁRIO", "TOTAL"]]
    subtotal = 0.0
    for item in items:
        if not item.get("enabled", True):
            continue
        quantity = float(item.get("quantity") or 0)
        unit_price = float(item.get("unit_price") or 0)
        line_total = quantity * unit_price
        subtotal += line_total
        name = escape(str(item.get("name") or "Serviço"))
        unit = escape(str(item.get("unit") or "un"))
        table_data.append([
            Paragraph(name, styles["body"]), f"{quantity:g} {unit}", money(unit_price), money(line_total),
        ])
    service_table = Table(table_data, colWidths=[79 * mm, 22 * mm, 34 * mm, 35 * mm], repeatRows=1, hAlign="LEFT")
    service_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("LEADING", (0, 0), (-1, 0), 10), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), .5, LINE), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("FONTSIZE", (1, 1), (-1, -1), 8), ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#435148")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(service_table)

    vat_rate = float(proposal.get("vat_rate") or 0)
    vat = subtotal * vat_rate / 100
    total = subtotal + vat
    totals = Table([
        ["Subtotal", money(subtotal)], [f"IVA ({vat_rate:g}%)", money(vat)], ["TOTAL", money(total)],
    ], colWidths=[46 * mm, 39 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("FONTNAME", (0, 0), (-1, 1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("TEXTCOLOR", (0, 0), (-1, -1), MUTED),
        ("LINEABOVE", (0, 2), (-1, 2), .8, GREEN), ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 2), (-1, 2), GREEN), ("TOPPADDING", (0, 2), (-1, 2), 8),
    ]))
    story.extend([Spacer(1, 4 * mm), totals, Paragraph("Condições comerciais", styles["section"])])
    validity = int(proposal.get("validity_days") or 30)
    execution = escape(str(proposal.get("execution_period") or "A definir pelo engenheiro responsável"))
    story.append(Paragraph(f"Validade da proposta: {validity} dias. Prazo de execução: {execution}.", styles["body"]))
    story.append(Paragraph(
        "O âmbito, os pressupostos técnicos, os acessos, as exclusões e as condições de pagamento devem ser confirmados antes da adjudicação.",
        styles["small"],
    ))
    story.extend([Spacer(1, 16 * mm), Paragraph("Com os melhores cumprimentos,", styles["body"]),
                  Spacer(1, 8 * mm), Paragraph("OZ — Diagnóstico e Engenharia", styles["body"])])
    document.build(story)
    return output.getvalue()
