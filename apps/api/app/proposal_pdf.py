"""Six-section OZ proposal PDF, styled after the supplied six-page reference."""

import html
from pathlib import Path
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
    BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)

from app.config import settings


GREEN = colors.HexColor("#155A49")
GREEN_HEX = "#155A49"
GREEN_LIGHT = colors.HexColor("#EAF2ED")
BODY = colors.HexColor("#48574E")
MUTED = colors.HexColor("#718078")
RULE = colors.HexColor("#D5DED7")
PAGE_WIDTH, PAGE_HEIGHT = A4
COMPANY_NAME_REFERENCE = "Diagnóstico, Levantamento e Controlo de Qualidade em Estruturas e Fundações, Lda."
COMPANY_ADDRESS_REFERENCE = "Rua Prof. Reinaldo dos Santos, 48 – B, 1500-508 Lisboa"
COMPANY_EMAIL_REFERENCE = "ger@oz-diagnostico.pt"
COMPANY_PHONE_REFERENCE = "213 563 371"
COMPANY_FAX_REFERENCE = "213 153 550"
COMPANY_WEBSITE_REFERENCE = "www.oz-diagnostico.pt"
PAYMENT_TERMS_REFERENCE = "40%, com a adjudicação. O restante a 30 dias da data da fatura, a emitir após o envio do relatório."
EXECUTION_PERIOD_REFERENCE = "Início dos trabalhos: a combinar. Duração da inspeção visual e elaboração do relatório: 3 semanas. Duração dos ensaios e elaboração do relatório respetivo: 5 semanas."
QUALITY_REFERENCE = "A nossa firma dispõe de um Sistema de Gestão da Qualidade concebido e implementado segundo a NP EN ISO 9001:2015, certificado pela APCER, no âmbito do levantamento de estruturas e fundações e diagnóstico das suas anomalias através de métodos não destrutivos."
AFFILIATIONS_REFERENCE = "A Oz é detentora do estatuto de Gestor da Qualidade LNEC e membro do GECoRPA — Grémio do Património. Saiba mais em www.oz-diagnostico.pt."
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
    def __init__(self, output: BytesIO, proposal_no: str):
        super().__init__(
            output, pagesize=A4, leftMargin=21 * mm, rightMargin=21 * mm,
            topMargin=58 * mm, bottomMargin=19 * mm, title=f"Proposta {proposal_no}",
            author=settings.company_name,
        )
        cover_frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height,
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover")
        inner_frame = Frame(self.leftMargin, self.bottomMargin, self.width,
                            PAGE_HEIGHT - 26 * mm - self.bottomMargin,
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="inner")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=self._draw_cover),
            PageTemplate(id="inner", frames=[inner_frame]),
        ])

    def _draw_cover(self, canvas: Any, doc: Any) -> None:
        canvas.saveState()
        masthead = Path(__file__).parent / "assets" / "oz_reference_letterhead.png"
        if masthead.exists():
            canvas.drawImage(str(masthead), 16 * mm, PAGE_HEIGHT - 54 * mm,
                             width=181 * mm, height=50.4 * mm,
                             preserveAspectRatio=True, mask="auto", anchor="c")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 6.4)
        contact = " · ".join(value for value in (
            settings.company_address or COMPANY_ADDRESS_REFERENCE,
            f"Tel.: {settings.company_phone or COMPANY_PHONE_REFERENCE}",
            f"Fax: {settings.company_fax or COMPANY_FAX_REFERENCE}",
            f"Email: {settings.company_email or COMPANY_EMAIL_REFERENCE}",
            f"URL: {settings.company_website or COMPANY_WEBSITE_REFERENCE}",
        ) if value)
        canvas.setFont("Helvetica", 5.4)
        canvas.drawString(21 * mm, 11 * mm, f"Escritório: {contact or settings.company_name}")
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
            self.setFont("Helvetica", 8)
            self.drawCentredString(PAGE_WIDTH / 2, 8 * mm, f"{page_number}/{page_count}")
            super().showPage()
        super().save()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("OZTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=13,
                                leading=16, textColor=colors.black, alignment=TA_LEFT, spaceBefore=2, spaceAfter=7),
        "subtitle": ParagraphStyle("OZSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=10,
                                    leading=13, textColor=BODY, spaceAfter=6),
        "body": ParagraphStyle("OZBody", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5,
                                leading=13, textColor=colors.HexColor("#161616"), spaceAfter=7, alignment=TA_LEFT),
        "small": ParagraphStyle("OZSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=8.2,
                                leading=10.4, textColor=BODY, spaceAfter=4),
        "section": ParagraphStyle("OZSection", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=10.5,
                                  leading=13, textColor=colors.black, spaceBefore=8, spaceAfter=5, keepWithNext=True),
        "subsection": ParagraphStyle("OZSubsection", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=9.5,
                                      leading=12, textColor=colors.black, spaceBefore=6, spaceAfter=3, keepWithNext=True),
        "label": ParagraphStyle("OZMetaLabel", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.4,
                                leading=9, textColor=colors.black, spaceAfter=1),
        "value": ParagraphStyle("OZMetaValue", parent=base["Normal"], fontName="Helvetica", fontSize=8.6,
                                leading=10.5, textColor=colors.black),
        "code": ParagraphStyle("OZCode", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8.2,
                               leading=10, textColor=GREEN),
        "right": ParagraphStyle("OZRight", parent=base["Normal"], fontName="Helvetica", fontSize=8.3,
                                leading=10, textColor=BODY, alignment=TA_RIGHT),
    }


def _section(title: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(_safe(title), styles["section"])


def _metadata_table(fields: dict[str, Any], proposal: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    label = lambda text: Paragraph(_safe(text), styles["label"])
    value = lambda text: Paragraph(_safe(text or "—"), styles["value"])
    rows = [
        [label("N.º ref."), value(proposal.get("proposal_no")), label("Data"), value(_date(proposal.get("created_at")))],
        [label("Para (To):"), value(fields.get("client_name") or "Cliente por identificar"), label("Tel. (Phone):"), value(fields.get("client_phone"))],
        [label("À Att.:"), value(fields.get("client_contact_name") or fields.get("sender_name")), label("Email:"), value(fields.get("client_email") or fields.get("client_contact_email"))],
        [label("DE (From):"), value(settings.company_name or COMPANY_NAME_REFERENCE), label("Tel. (Phone):"), value(settings.company_phone or COMPANY_PHONE_REFERENCE)],
        [label("CC.:"), value(fields.get("sender_organization") or "—"), label("Email:"), value(settings.company_email or COMPANY_EMAIL_REFERENCE)],
        [label("ASS. (RE):"), value(fields.get("source_subject") or fields.get("project_name") or "Pedido de proposta"), "", ""],
    ]
    client_label = fields.get("client_name") or "Cliente por identificar"
    if fields.get("client_tax_id"):
        client_label = f"{client_label} · NIF/NUIT {fields['client_tax_id']}"
    rows[1][1] = value(client_label)
    table = Table(rows, colWidths=[25 * mm, 61 * mm, 24 * mm, 58 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("SPAN", (1, 5), (3, 5)),
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


def build_proposal_pdf(request: dict[str, Any], proposal: dict[str, Any], items: list[dict[str, Any]],
                       analysis: dict[str, Any] | None = None) -> bytes:
    """Create the branded proposal with the six editorial sections of the reference PDF."""
    output = BytesIO()
    fields = request.get("extracted_fields") or {}
    analysis_fields = (analysis or {}).get("extracted") or {}
    diagnosis = analysis_fields.get("technical_diagnosis") or {}
    candidates = diagnosis.get("candidates") or []
    technical_context = " ".join(str(fields.get(key) or "") for key in (
        "objective", "problem_type", "problem_summary", "categories", "requested_services",
    )).casefold()
    structural_scope = bool(candidates) or any(term in technical_context for term in (
        "estrutura", "estrutural", "betão", "betao", "concreto", "alvenaria", "fissur",
        "humidade", "infiltração", "infiltracao", "armadura", "fundação", "fundacao",
    ))
    client = _plain(fields.get("client_name"), "Cliente")
    proposal_no = _plain(proposal.get("proposal_no"), "Por atribuir")
    styles = _styles()
    story: list[Any] = []

    # Cover page follows the correspondence block and numbered sections in the reference.
    story.extend([
        _metadata_table(fields, proposal, styles), Spacer(1, 3 * mm),
        Paragraph(f"Proposta N.º: {_safe(proposal_no)}", styles["title"]),
        _paragraph(f"Exmo.(a) Senhor(a) {client},", styles["body"]),
        _paragraph("Na sequência da vossa solicitação, apresentamos as condições em que poderemos prestar a nossa colaboração nos trabalhos em referência. O âmbito e os métodos propostos serão ajustados de acordo com a informação disponível e carecem de validação do responsável técnico.", styles["body"]),
        _section("1. Objeto", styles),
        _paragraph(fields.get("objective"), styles["body"],
                   "Definição do objeto técnico por confirmar com base na descrição do pedido e nos elementos da obra."),
    ])
    if fields.get("problem_summary"):
        story.append(_paragraph(f"Problema descrito: {fields['problem_summary']}", styles["body"]))
    symptom_locations = fields.get("symptom_locations") or []
    if isinstance(symptom_locations, str):
        symptom_locations = [line.strip() for line in symptom_locations.splitlines() if line.strip()]
    if symptom_locations:
        story.append(_paragraph(f"Localização das anomalias indicada: {', '.join(map(str, symptom_locations))}.", styles["body"]))
    requested_services = fields.get("requested_services") or []
    story.append(Paragraph("Serviços indicados no pedido", styles["subsection"]))
    story.extend(_bullets(requested_services, styles,
                          "O cliente não indicou serviços específicos; o âmbito proposto deve ser definido após revisão técnica."))
    story.extend([
        _section("2. Considerações prévias", styles),
        _paragraph("A descrição seguinte resume os elementos comunicados pelo cliente. A informação disponibilizada não permite confirmar mecanismos anómalos ou o desempenho atual da construção; as observações e recomendações dependem da inspeção e dos ensaios aprovados.", styles["body"]),
    ])
    known = []
    if fields.get("building_area_m2"):
        known.append(f"Área aproximada indicada: {fields['building_area_m2']} m².")
    if fields.get("storey_count") is not None:
        known.append(f"Número de pisos indicado: {fields['storey_count']}.")
    if fields.get("construction_year"):
        known.append(f"Ano de construção indicado: {fields['construction_year']}.")
    if fields.get("basement_count") is not None:
        known.append(f"Número de caves indicado: {fields['basement_count']}.")
    if fields.get("location"):
        known.append(f"Localização indicada: {fields['location']}.")
    story.extend(_bullets(known, styles, "Ano de construção, configuração e elementos de projeto não informados."))
    story.extend([NextPageTemplate("inner"), PageBreak()])

    # Page 2 continues the assumptions and introduces the inspection scope.
    story.extend([
        _section("2. Considerações prévias (continuação)", styles),
    ])
    if fields.get("constraints"):
        story.append(Paragraph("Restrições e condições mencionadas", styles["subsection"]))
        story.extend(_bullets(fields.get("constraints"), styles, "Sem restrições comunicadas."))
    story.extend([
        Paragraph("Documentação a disponibilizar", styles["subsection"]),
        _paragraph("Peças desenhadas e alterações executadas, relatórios de inspeções ou ensaios anteriores, registos de manutenção e condições de acesso às zonas a observar. A ausência destes elementos pode limitar a interpretação dos resultados.", styles["body"]),
        Paragraph("Limites da avaliação", styles["subsection"]),
        _paragraph("As conclusões dependem das zonas acessíveis, das condições encontradas e dos ensaios aprovados. Ensaios destrutivos, trabalhos de reparação e análises laboratoriais só serão realizados se estiverem expressamente incluídos no âmbito e autorizados.", styles["body"]),
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
    if structural_scope:
        story.extend([
            _paragraph("A inspeção visual, por amostragem das zonas acessíveis, visa identificar e caracterizar anomalias representativas ou relevantes para o desempenho e durabilidade da estrutura.", styles["body"]),
            _paragraph("Poderão ser registadas, entre outras manifestações observáveis, fissuras e respetiva orientação/abertura, deformações, destacamentos de betão, corrosão aparente das armaduras, lacunas e deficiências gerais.", styles["body"]),
            _paragraph("O levantamento poderá recorrer a régua de fissuras, fita métrica, escala fotográfica e percussão ligeira, quando adequada. Os registos fotográficos documentarão os pontos observados; a seleção final dos meios depende das condições encontradas.", styles["body"]),
            _paragraph("O relatório descreverá os trabalhos e observações, a análise dos resultados, as limitações e recomendações para a estratégia de intervenção futura. Poderá incluir proposta de plano de inspeção e ensaios complementares, se necessário.", styles["body"]),
            _paragraph("O relatório do estudo preliminar será fornecido em suporte digital.", styles["body"]),
        ])
    story.append(Paragraph("3.2 Ensaios complementares", styles["subsection"]))
    story.append(_paragraph("Os ensaios são recomendações preliminares, dependentes da observação local, do acesso e da aprovação do cliente. A sua inclusão nos honorários deve ser confirmada antes de adjudicação.", styles["body"]))
    story.append(PageBreak())

    # Page 3 describes recommended test methods grounded in linked catalog codes.
    story.extend([
        Paragraph("3.2.1 Métodos de ensaio propostos", styles["subsection"]),
    ])
    unique_tests: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        for test in candidate.get("tests") or []:
            if test.get("code"):
                unique_tests[str(test["code"])] = test
    if unique_tests:
        for test in unique_tests.values():
            test_code = str(test.get("code") or "")
            story.append(Paragraph(
                f"<b>{_safe(test_code)}</b> — {_safe(test.get('name'))}", styles["body"],
            ))
            method = TEST_METHODS.get(test_code)
            if method:
                story.append(_paragraph(method, styles["body"]))
            else:
                story.append(_paragraph("Metodologia, amostragem e número de leituras a definir pelo responsável técnico após inspeção e consulta às condições do local.", styles["small"]))
    else:
        story.append(_paragraph(
            "Não foi possível identificar um ensaio codificado com evidência suficiente na base de conhecimento. A metodologia deve ser definida pelo engenheiro responsável após análise do pedido e visita técnica.",
            styles["body"],
        ))
    story.append(_paragraph("Os ensaios não devem ser entendidos como contratados até constarem das linhas de honorários e serem aprovados pelo cliente.", styles["small"]))
    story.append(_paragraph("A metodologia ou técnica poderá ser ajustada após a inspeção quando as condições observadas o justifiquem; qualquer substituição relevante será submetida à aprovação do cliente antes da execução.", styles["small"]))
    example_images = []
    if "ENS-12" in unique_tests:
        example_images.append(("oz_reference_pacometer.jpg", "Fig. 1 — Medição do recobrimento das armaduras com pacómetro."))
    if "ENS-16" in unique_tests:
        example_images.append(("oz_reference_carbonation.jpg", "Fig. 2 — Determinação da profundidade de carbonatação do betão."))
    if example_images:
        cells = []
        for filename, caption in example_images:
            asset = Path(__file__).parent / "assets" / filename
            cells.append([
                Image(str(asset), width=78 * mm, height=59 * mm, kind="proportional"),
                Paragraph(_safe(caption), styles["small"]),
            ])
        photo_rows = [[cell[0] for cell in cells], [cell[1] for cell in cells]]
        photo_table = Table(photo_rows, colWidths=[82 * mm] * len(cells), hAlign="LEFT")
        photo_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(Spacer(1, 4 * mm))
        story.append(_paragraph("Exemplos visuais dos métodos (imagens do documento de referência)", styles["small"]))
        story.append(photo_table)
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
    story.extend([
        _section("4. Preços", styles),
        _paragraph("Para a prestação dos trabalhos propostos, apresentam-se na página seguinte as verbas discriminadas. As recomendações técnicas só integram o âmbito contratado quando incluídas nas linhas abaixo.", styles["body"]),
    ])
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
    story.extend([Spacer(1, 4 * mm), totals, Paragraph("Notas", styles["subsection"])])
    fee_notes = [
        "Os preços consideram a mobilização de pessoal qualificado, equipamento e coordenação técnica, nos limites das linhas contratadas.",
        "Não inclui verificação estrutural, projeto de reforço ou reparações fora do âmbito expressamente descrito.",
        "Meios de acesso, energia elétrica e apoio de andaime só estão incluídos quando indicados nas linhas de honorários.",
        "As quantidades de ensaios são estimativas mínimas; resultados divergentes podem limitar a fiabilidade das conclusões.",
        "O cliente disponibilizará, na adjudicação, cópia digital dos desenhos de projeto existentes e informação sobre instalações embebidas.",
        "A reposição de furos e roços limita-se ao que estiver indicado nas linhas contratadas; materiais de revestimento não são repostos salvo indicação expressa.",
        "Danos em equipamentos embebidos não identificados pelo cliente e condições estruturais ocultas devem ser avaliados caso a caso.",
        "Atrasos não imputáveis à OZ podem alterar prazos e custos; qualquer custo adicional será comunicado para aprovação prévia.",
        "O subtotal não inclui IVA; o imposto é apresentado separadamente à taxa legal configurada para a proposta.",
    ]
    story.extend(Paragraph(f"•  {_safe(note)}", styles["small"]) for note in fee_notes)
    story.extend([
        Paragraph("5. Condições de pagamento", styles["subsection"]),
        _paragraph(settings.proposal_payment_terms, styles["body"], PAYMENT_TERMS_REFERENCE),
    ])
    requested_conditions = fields.get("requested_conditions") or []
    if isinstance(requested_conditions, str):
        requested_conditions = [requested_conditions]
    if requested_conditions:
        story.append(Paragraph("Condições pedidas pelo cliente", styles["subsection"]))
        story.extend(_bullets(requested_conditions, styles, "Sem condições adicionais indicadas."))
    story.append(PageBreak())

    # 6. Delivery terms, exclusions and formal approval space.
    story.extend([
        _section("6. Prazos", styles),
        _paragraph(_plain(proposal.get("execution_period"), settings.proposal_execution_period or EXECUTION_PERIOD_REFERENCE), styles["body"]),
        _paragraph(f"Validade da proposta: {int(proposal.get('validity_days') or 60)} dias.", styles["body"]),
        _section("7. Exclusões", styles),
        _paragraph("São da responsabilidade do cliente, salvo inclusão expressa nas linhas de honorários:", styles["body"]),
    ])
    story.extend([
        *_bullets([
            "Autorizações necessárias para a livre circulação do pessoal.",
            "Remoção de obstáculos aos elementos a inspecionar.",
            "Eventual bombagem de água dos pisos enterrados.",
            "Eventual atualização dos desenhos existentes.",
            "Tudo o que não estiver incluído na presente proposta.",
        ], styles, "Sem exclusões adicionais."),
        Paragraph("Sistema de qualidade e associações profissionais", styles["subsection"]),
        _paragraph(settings.proposal_quality_statement or QUALITY_REFERENCE, styles["small"]),
        _paragraph(settings.proposal_affiliations_statement or AFFILIATIONS_REFERENCE, styles["small"]),
        Paragraph("Entregável e validação técnica", styles["subsection"]),
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

    document = ProposalDocTemplate(output, proposal_no)
    document.build(story, canvasmaker=NumberedCanvas)
    return output.getvalue()
