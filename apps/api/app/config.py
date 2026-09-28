from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    resend_api_key: str = ""
    email_from: str = ""
    web_origin: str = "http://localhost:3000"
    company_name: str = "OZ Diagnóstico e Engenharia"
    company_address: str = ""
    company_email: str = ""
    company_phone: str = ""
    proposal_signatory: str = ""
    proposal_payment_terms: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)


settings = Settings()
