from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    # Alternativa à OpenAI: qualquer API compatível com "chat/completions"
    # (Gemini, Groq, OpenRouter, Ollama local...). Se LLM_BASE_URL estiver preenchido, é usada em vez da OpenAI.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_fallback_model: str = ""
    resend_api_key: str = ""
    email_from: str = ""
    web_origin: str = "http://localhost:3000"
    company_name: str = "Diagnóstico, Levantamento e Controlo de Qualidade em Estruturas e Fundações, Lda."
    company_address: str = "Rua Prof. Reinaldo dos Santos, 48 – B, 1500-508 Lisboa"
    company_email: str = "ger@oz-diagnostico.pt"
    company_phone: str = "213 563 371"
    company_fax: str = "213 153 550"
    company_website: str = "www.oz-diagnostico.pt"
    proposal_signatory: str = ""
    proposal_payment_terms: str = "40%, com a adjudicação.\nO restante a 30 dias da data da fatura, a emitir após o envio do relatório."
    proposal_execution_period: str = "Início dos trabalhos: a combinar.\nDuração da inspeção visual e elaboração do relatório: 3 semanas.\nDuração dos ensaios e elaboração do relatório respetivo: 5 semanas."
    proposal_quality_statement: str = "A nossa firma dispõe de um Sistema de Gestão da Qualidade concebido e implementado segundo a NP EN ISO 9001:2015, certificado pela APCER, no âmbito do levantamento de estruturas e fundações e diagnóstico das suas anomalias através de métodos não destrutivos."
    proposal_affiliations_statement: str = "A Oz é detentora do estatuto de Gestor da Qualidade LNEC e membro do GECoRPA — Grémio do Património. Saiba mais em www.oz-diagnostico.pt."

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url.strip() or self.openai_api_key.strip())

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


settings = Settings()
