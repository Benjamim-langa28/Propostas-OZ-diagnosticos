"""Six-section OZ proposal PDF, styled after the supplied six-page reference."""

import html
from datetime import date, datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

from app.config import settings


GREEN = colors.HexColor("#155A49")
GREEN_HEX = "#155A49"
GREEN_LIGHT = colors.HexColor("#EAF2ED")
INK = colors.HexColor("#24352E")
BODY = colors.HexColor("#48574E")
MUTED = colors.HexColor("#718078")
RULE = colors.HexColor("#D5DED7")
PALE = colors.HexColor("#F6F8F5")
PAGE_WIDTH, PAGE_HEIGHT = A4
TEST_METHODS = {
    "ENS-12": "Método indicativo: localizar armaduras e medir o recobrimento em pontos definidos durante a inspeção, com equipamento pacométrico. Ensaio não destrutivo; a malha e o número de leituras são acordados no local.",
    "ENS-16": "Método indicativo: expor uma superfície fresca de betão, aplicar indicador de fenolftaleína e registar a profundidade da frente de carbonatação para comparação com o recobrimento medido.",
    "ENS-17": "Método indicativo: recolher amostras de material em perfis de profundidade (três níveis, a confirmar com o laboratório) e determinar o teor de cloretos, registando a posição e profundidade de cada amostra.",
    "ENS-18": "Método indicativo: extrair carotes em pontos autorizados e determinar a resistência à compressão em laboratório segundo o método aplicável. A extração deixa zonas a reparar e requer aprovação prévia.",
}


def _money(value: Any) -> str:
    amount = float(value or 0)
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _plain(value: Any, fallback: str = "") -> str:
    return str(value).strip() if value not in (None, "") else fallback


def _safe(value: Any) -> str:
    return html.escape(_plain(value)).replace("\n", "<br/>")


def _date(value: Any = None) -> str:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return date.today().strftime("%d/%m/%Y")


def _paragraph(text: Any, style: ParagraphStyle, fallback: str = "") -> Paragraph:
    return Paragraph(_safe(text if text not in (None, "") else fallback), style)


def _bullets(values: Any, styles: dict[str, ParagraphStyle], empty: str) -> list[Any]:
    if not isinstance(values, list):
        values = [values] if values else []
    values = [str(value).strip() for value in values if str(value).strip()]
    if not values:
        return [_paragraph(empty, styles["small"])]
    return [Paragraph(f"<font color='{GREEN_HEX}'><b>•</b></font>  {_safe(value)}", styles["body"]) for value in values]


class ProposalDocTemplate(BaseDocTemplate):
    def __init__(self, output: BytesIO, proposal_no: str, proposal_date: str):
        super().__init__(
            output, pagesize=A4, leftMargin=19 * mm, rightMargin=19 * mm,
            topMargin=34 * mm, bottomMargin=23 * mm, title=f"Proposta {proposal_no}",
            author=settings.company_name,
        )
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="main")
        self.addPageTemplates([PageTemplate(id="oz", frames=[frame], onPage=self._draw_page)])
        self.proposal_no = proposal_no
        self.proposal_date = proposal_date

    def _draw_page(self, canvas: Any, doc: Any) -> None:
        canvas.saveState()
        # A compact, reusable masthead mirrors the reference's green wordmark and right-aligned reference block.
        x = 19 * mm
        y = PAGE_HEIGHT - 23 * mm
        canvas.setFillColor(GREEN)
        canvas.roundRect(x, y - 1.5 * mm, 13 * mm, 13 * mm, 1.7 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(x + 6.5 * mm, y + 3 * mm, "OZ")
        canvas.setFillColor(INK)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(x + 17 * mm, y + 6 * mm, "OZ Propostas")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica-Bold", 5.6)
        canvas.drawString(x + 17 * mm, y + 1.5 * mm, "DIAGNÓSTICO E ENGENHARIA")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawRightString(PAGE_WIDTH - 19 * mm, y + 6 * mm, f"PROPOSTA  {self.proposal_no}")
        canvas.drawRightString(PAGE_WIDTH - 19 * mm, y + 1.5 * mm, self.proposal_date)
        canvas.setStrokeColor(GREEN)
        canvas.setLineWidth(.8)
        canvas.line(19 * mm, PAGE_HEIGHT - 29 * mm, PAGE_WIDTH - 19 * mm, PAGE_HEIGHT - 29 * mm)

        footer_y = 15 * mm
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(.55)
        canvas.line(19 * mm, footer_y + 4 * mm, PAGE_WIDTH - 19 * mm, footer_y + 4 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 6.8)
        contact = " · ".join(value for value in (settings.company_address, settings.company_email, settings.company_phone) if value)
        canvas.drawString(19 * mm, footer_y - 1 * mm, contact or settings.company_name)
        canvas.restoreState()


class NumberedCanvas(pdfcanvas.Canvas):
    """Canvas that adds the final page count after ReportLab paginates."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for page_number, state in enumerate(self._saved_page_states, start=1):
            self.__dict__.update(state)
            self.setFillColor(MUTED)
            self.setFont("Helvetica", 6.8)
            self.drawRightString(PAGE_WIDTH - 19 * mm, 14 * mm, f"{page_number} / {page_count}")
            super().showPage()
        super().save()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("OZTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=19,
                                leading=23, textColor=INK, alignment=TA_LEFT, spaceBefore=2, spaceAfter=9),
        "subtitle": ParagraphStyle("OZSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=8.5,
                                    leading=12, textColor=MUTED, spaceAfter=8),
        "body": ParagraphStyle("OZBody", parent=base["BodyText"], fontName="Helvetica", fontSize=8.6,
                                leading=12.3, textColor=BODY, spaceAfter=6),
        "small": ParagraphStyle("OZSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=7.1,
                                leading=10, textColor=MUTED, spaceAfter=4),
        "section": ParagraphStyle("OZSection", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.2,
                                  leading=14, textColor=GREEN, spaceBefore=8, spaceAfter=6, keepWithNext=True),
        "subsection": ParagraphStyle("OZSubsection", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=9.2,
                                      leading=12, textColor=INK, spaceBefore=6, spaceAfter=4, keepWithNext=True),
        "label": ParagraphStyle("OZMetaLabel", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=6.2,
                                leading=8, textColor=MUTED, spaceAfter=2),
        "value": ParagraphStyle("OZMetaValue", parent=base["Normal"], fontName="Helvetica", fontSize=7.8,
                                leading=10.5, textColor=INK),
        "code": ParagraphStyle("OZCode", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.3,
                               leading=9, textColor=GREEN),
        "right": ParagraphStyle("OZRight", parent=base["Normal"], fontName="Helvetica", fontSize=7.8,
                                leading=10, textColor=MUTED, alignment=TA_RIGHT),
    }


def _section(title: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_safe(title), styles["section"])


def _meta_cell(label: str, value: Any, styles: dict[str, ParagraphStyle]) -> list[Any]:
    return [Paragraph(_safe(label.upper()), styles["label"]), Paragraph(_safe(value or "—"), styles["value"])]


def _metadata_table(fields: dict[str, Any], proposal: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    rows = [
        [_meta_cell("Para / Cliente", fields.get("client_name") or "Cliente por identificar", styles),
         _meta_cell("N.º da proposta / data", f"{_plain(proposal.get('proposal_no'))} · {_date(proposal.get('created_at'))}", styles)],
        [_meta_cell("A/C", fields.get("client_contact_name") or fields.get("sender_name") or "—", styles),
         _meta_cell("Email", fields.get("client_email") or fields.get("client_contact_email") or "—", styles)],
        [_meta_cell("Telefone / NIF", " · ".join(x for x in [fields.get("client_phone"), fields.get("client_tax_id")] if x) or "—", styles),
         _meta_cell("Local da obra", fields.get("location") or "Por confirmar", styles)],
        [_meta_cell("Obra / projeto", fields.get("project_name") or "Por identificar", styles),
         _meta_cell("Assunto / referência de origem", fields.get("source_subject") or "Pedido de proposta", styles)],
    ]
    table = Table(rows, colWidths=[83 * mm, 83 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), .55, RULE),
        ("INNERGRID", (0, 0), (-1, -1), .45, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _code_list(rows: Any, styles: dict[str, ParagraphStyle], empty: str) -> list[Any]:
    if not rows:
        return [_paragraph(empty, styles["small"])]
    result = []
    for row in rows:
        code = _safe(row.get("code"))
        name = _safe(row.get("name"))
        extra = f" · {_safe(row.get('test_group'))}" if row.get("test_group") else ""
        result.append(Paragraph(f"<font color='{GREEN_HEX}'><b>{code}</b></font> — {name}{extra}", styles["body"]))
    return result


def _format_list_as_text(values: Any) -> str:
    if not isinstance(values, list):
        values = [values] if values else []
    return "\n".join(str(value) for value in values if str(value).strip())


def build_proposal_pdf(request: dict[str, Any], proposal: dict[str, Any], items: list[dict[str, Any]],
                       analysis: dict[str, Any] | None = None) -> bytes:
    """Create the branded proposal with the six editorial sections of the reference PDF."""
    output = BytesIO()
    fields = request.get("extracted_fields") or {}
    analysis_fields = (analysis or {}).get("extracted") or {}
    diagnosis = analysis_fields.get("technical_diagnosis") or {}
    candidates = diagnosis.get("candidates") or []
    project = _plain(fields.get("project_name") or request.get("title"), "Obra / projeto")
    client = _plain(fields.get("client_name"), "Cliente")
    proposal_no = _plain(proposal.get("proposal_no"), "Por atribuir")
    proposal_date = _date(proposal.get("created_at") or request.get("created_at"))
    styles = _styles()
    story: list[Any] = []

    # 1. Letter, addressee and object of the proposal.
    story.extend([
        Paragraph("PROPOSTA TÉCNICA", styles["title"]),
        Paragraph(_safe(project), styles["subtitle"]),
        _metadata_table(fields, proposal, styles), Spacer(1, 8 * mm),
        _paragraph(f"Exmo.(a) Senhor(a) {client},", styles["body"]),
        _paragraph("Na sequência do pedido recebido, apresentamos a proposta para a prestação de serviços de diagnóstico e engenharia descrita neste documento. O âmbito, os métodos e os valores abaixo devem ser revistos pelo responsável técnico antes da aprovação.", styles["body"]),
        _section("1. Objeto", styles),
        _paragraph(fields.get("objective"), styles["body"],
                   "Definição do objeto técnico por confirmar com base na descrição do pedido e nos elementos da obra."),
    ])
    requested_services = fields.get("requested_services") or []
    story.append(Paragraph("Serviços indicados no pedido", styles["subsection"]))
    story.extend(_bullets(requested_services, styles,
                          "O cliente não indicou serviços específicos; o âmbito proposto deve ser definido após revisão técnica."))
    story.append(PageBreak())

    # 2. Information and assumptions supplied with the request.
    story.extend([
        _section("2. Considerações prévias", styles),
        _paragraph("A presente proposta foi estruturada a partir do texto e dos anexos associados ao pedido. Os elementos descritos pelo cliente são tratados como informação a verificar durante a inspeção; não constituem confirmação de uma causa ou patologia.", styles["body"]),
    ])
    known = []
    if fields.get("construction_year"):
        known.append(f"Ano de construção indicado: {fields['construction_year']}.")
    if fields.get("basement_count") is not None:
        known.append(f"Número de caves indicado: {fields['basement_count']}.")
    if fields.get("location"):
        known.append(f"Localização indicada: {fields['location']}.")
    story.extend(_bullets(known, styles, "Ano de construção, configuração estrutural e elementos de projeto não fornecidos no pedido."))
    if fields.get("constraints"):
        story.append(Paragraph("Restrições e condições mencionadas", styles["subsection"]))
        story.extend(_bullets(fields.get("constraints"), styles, "Sem restrições comunicadas."))
    story.extend([
        Paragraph("Documentação a disponibilizar", styles["subsection"]),
        _paragraph("Peças desenhadas e alterações executadas, relatórios de inspeções ou ensaios anteriores, registos de manutenção e condições de acesso às zonas a observar. A ausência destes elementos pode limitar a interpretação dos resultados.", styles["body"]),
        Paragraph("Limites da avaliação", styles["subsection"]),
        _paragraph("As conclusões dependem das zonas acessíveis, das condições encontradas e dos ensaios aprovados. Ensaios destrutivos, trabalhos de reparação e análises laboratoriais só serão realizados se estiverem expressamente incluídos no âmbito e autorizados.", styles["body"]),
    ])
    story.append(PageBreak())

    # 3. Technical method, with recommended tests linked to knowledge-base codes.
    story.extend([
        _section("3. Condições técnicas", styles),
        _paragraph("A intervenção deve confirmar as manifestações observáveis, registar a sua localização e extensão e definir os ensaios adequados. A seleção abaixo decorre da correspondência preliminar com a base técnica da aplicação.", styles["body"]),
        Paragraph("3.1 Estudo preliminar com inspeção visual", styles["subsection"]),
    ])
    visual_scope = [
        "Recolha e análise da informação e documentação fornecidas pelo cliente.",
        "Inspeção visual das zonas acessíveis e registo fotográfico das anomalias observadas.",
        "Mapeamento preliminar, por elemento e localização, das manifestações observáveis.",
        "Definição de ensaios complementares e elaboração do relatório técnico previsto no âmbito aprovado.",
    ]
    story.extend(_bullets(visual_scope, styles, "Inspeção e entregáveis a confirmar pelo responsável técnico."))
    story.append(Paragraph("3.2 Ensaios complementares sugeridos", styles["subsection"]))
    unique_tests: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        for test in candidate.get("tests") or []:
            if test.get("code"):
                unique_tests[str(test["code"])] = test
    story.append(_paragraph(
        "Os ensaios são recomendações preliminares, dependentes da observação local, do acesso e da aprovação do cliente. A sua inclusão nos honorários deve ser confirmada antes de adjudicação.",
        styles["body"],
    ))
    if unique_tests:
        for test in unique_tests.values():
            test_code = str(test.get("code") or "")
            story.append(Paragraph(
                f"<font color='{GREEN_HEX}'><b>{_safe(test_code)}</b></font> — {_safe(test.get('name'))}",
                styles["body"],
            ))
            method = TEST_METHODS.get(test_code)
            if method:
                story.append(_paragraph(method, styles["small"]))
    else:
        story.append(_paragraph(
            "Não foi possível identificar um ensaio codificado com evidência suficiente na base de conhecimento.",
            styles["small"],
        ))
    story.append(PageBreak())

    # 4. Pathology map, evidence, possible causes and solutions, each with catalog codes.
    story.extend([
        _section("3.3 Mapeamento preliminar de patologias", styles),
        _paragraph("A percentagem apresentada é uma medida de aderência textual ao catálogo. É uma triagem assistida, não a probabilidade de a patologia existir nem um diagnóstico confirmado.", styles["small"]),
    ])
    if not candidates:
        story.append(_paragraph(diagnosis.get("message") or "Não há correspondência codificada suficiente. O responsável técnico deve definir a classificação e os ensaios após análise do pedido e inspeção.", styles["body"]))
    for candidate in candidates[:2]:
        severity_range = f"Severidade indicativa {candidate.get('severity_min', '—')}–{candidate.get('severity_max', '—')}"
        candidate_title = Table([[Paragraph(
            f"<font color='{GREEN_HEX}'><b>{_safe(candidate.get('code'))}</b></font>  {_safe(candidate.get('name'))}", styles["body"]),
            Paragraph(f"{int(candidate.get('match_percent') or 0)}%<br/><font size='6'>aderência</font>", styles["right"])]],
            colWidths=[139 * mm, 27 * mm])
        candidate_title.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GREEN_LIGHT), ("BOX", (0, 0), (-1, -1), .5, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        severity_names = ", ".join(_plain(level.get("name")) for level in candidate.get("severity") or [] if level.get("name"))
        severity_action = next((level.get("action") for level in reversed(candidate.get("severity") or []) if level.get("action")), None)
        block: list[Any] = [candidate_title,
            _paragraph(f"Grupo: {candidate.get('group') or '—'} · {severity_range}" + (f" · {severity_names}" if severity_names else ""), styles["small"])]
        if severity_action:
            block.append(_paragraph(f"Ação indicativa associada ao nível: {severity_action}", styles["small"]))
        evidence = candidate.get("evidence") or []
        if evidence:
            block.extend([Paragraph("Indício(s) no pedido", styles["subsection"]), *_bullets(evidence, styles, "Sem excerto direto.")])
        block.extend([Paragraph("Causas possíveis a verificar", styles["subsection"]),
                      *_code_list(candidate.get("causes"), styles, "Sem causas ligadas a esta entrada da base técnica."),
                      Paragraph("Ensaios associados", styles["subsection"]),
                      *_code_list(candidate.get("tests"), styles, "Sem ensaio codificado associado."),
                      Paragraph("Soluções de referência, condicionadas aos resultados", styles["subsection"]),
                      *_code_list(candidate.get("solutions"), styles, "Sem solução codificada associada."),
                      _paragraph("Causas e soluções são hipóteses de trabalho. A decisão depende da confirmação no local e dos resultados dos ensaios.", styles["small"]),
                      Spacer(1, 3 * mm)])
        story.extend(block)
    story.append(PageBreak())

    # 5. Commercial scope and itemized fees.
    story.extend([
        _section("4. Honorários", styles),
        _paragraph("Os valores abaixo correspondem às linhas ativas da proposta. Quantidades, unidades, preço e inclusão de ensaios devem ser confirmados antes da aprovação.", styles["body"]),
    ])
    active_items = [item for item in items if item.get("enabled", True)]
    table_data = [[Paragraph("DESCRIÇÃO / SERVIÇO", styles["label"]), Paragraph("QTD.", styles["label"]),
                   Paragraph("PREÇO UNITÁRIO", styles["label"]), Paragraph("TOTAL", styles["label"])]]
    subtotal = 0.0
    for item in active_items:
        quantity = float(item.get("quantity") or 0)
        unit_price = float(item.get("unit_price") or 0)
        line_total = quantity * unit_price
        subtotal += line_total
        detail = _safe(item.get("name") or "Serviço")
        if item.get("technical_basis"):
            detail += f"<br/><font size='6.5' color='#718078'>{_safe(item.get('technical_basis'))}</font>"
        table_data.append([Paragraph(detail, styles["body"]), f"{quantity:g} {_safe(item.get('unit') or 'un')}",
                           _money(unit_price), _money(line_total)])
    if not active_items:
        table_data.append([Paragraph("Âmbito e honorários por preencher após revisão técnica.", styles["body"]), "—", "—", "—"])
    price_table = Table(table_data, colWidths=[80 * mm, 23 * mm, 32 * mm, 31 * mm], repeatRows=1, hAlign="LEFT")
    price_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GREEN_LIGHT), ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
        ("BOX", (0, 0), (-1, -1), .5, RULE), ("INNERGRID", (0, 0), (-1, -1), .4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(price_table)
    vat_rate = float(proposal.get("vat_rate") or 0)
    vat = subtotal * vat_rate / 100
    totals = Table([
        ["Subtotal", _money(subtotal)], [f"IVA ({vat_rate:g}%)", _money(vat)],
        [Paragraph("TOTAL", styles["code"]), Paragraph(f"<b>{_money(subtotal + vat)}</b>", styles["right"])],
    ], colWidths=[42 * mm, 34 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"), ("TEXTCOLOR", (0, 0), (-1, 1), MUTED),
        ("FONTSIZE", (0, 0), (-1, 1), 8), ("LINEABOVE", (0, 2), (-1, 2), .8, GREEN),
        ("TOPPADDING", (0, 2), (-1, 2), 7),
    ]))
    story.extend([Spacer(1, 5 * mm), totals, PageBreak()])

    # 6. Commercial conditions, exclusions and formal approval space.
    story.extend([
        _section("4.1 Condições comerciais", styles),
        _paragraph(f"Validade da proposta: {int(proposal.get('validity_days') or 30)} dias. Prazo estimado: {_plain(proposal.get('execution_period'), 'a definir após confirmação do âmbito, acessos e disponibilidade do cliente')}.", styles["body"]),
        Paragraph("Condições de pagamento", styles["subsection"]),
        _paragraph(settings.proposal_payment_terms,
                   styles["body"], "Método e calendário de pagamento a confirmar antes da aprovação da proposta."),
        Paragraph("Condições pedidas pelo cliente", styles["subsection"]),
    ])
    requested_conditions = fields.get("requested_conditions") or []
    if isinstance(requested_conditions, str):
        requested_conditions = [requested_conditions]
    story.extend(_bullets(requested_conditions, styles,
                          "Forma e calendário de pagamento devem ser confirmados pelo responsável antes de emitir a versão final."))
    story.extend([
        Paragraph("Pressupostos e exclusões a confirmar", styles["subsection"]),
        *_bullets([
            "Autorizações e acesso às zonas de trabalho a coordenar com o cliente.",
            "Desobstrução, meios auxiliares e bombagem de água não incluídos salvo indicação expressa nas linhas de honorários.",
            "Atualização de desenhos, reparações e trabalhos fora do âmbito descrito não incluídos nesta proposta.",
            "Ensaios destrutivos ou análises laboratoriais dependem de autorização e orçamento aprovado.",
        ], styles, "Sem exclusões adicionais."),
        Paragraph("Entregável e validação", styles["subsection"]),
        _paragraph("Prevê-se a emissão de relatório técnico com o âmbito, observações e resultados dos serviços efetivamente contratados, limitações encontradas e recomendações decorrentes. As patologias, causas, ensaios e soluções aqui mapeados são preliminares e carecem de validação pelo engenheiro responsável.", styles["body"]),
        Spacer(1, 6 * mm),
        _paragraph("Com os melhores cumprimentos,", styles["body"]),
        Spacer(1, 15 * mm),
    ])
    signatory = _plain(settings.proposal_signatory)
    if signatory:
        story.append(_paragraph(signatory, styles["body"]))
    story.extend([
        Table([[""], [Paragraph("Engenheiro responsável / assinatura", styles["small"])]],
              colWidths=[78 * mm], rowHeights=[12 * mm, 6 * mm], style=TableStyle([
                  ("LINEABOVE", (0, 1), (0, 1), .5, MUTED), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                  ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
              ])),
        Spacer(1, 6 * mm),
        _paragraph(f"Aceitação do cliente: {client} · Data: ____ / ____ / ______ · Assinatura: ______________________________", styles["small"]),
    ])

    document = ProposalDocTemplate(output, proposal_no, proposal_date)
    document.build(story, canvasmaker=NumberedCanvas)
    return output.getvalue()
