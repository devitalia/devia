from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "devia-api"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8787
    mail_fetch_limit: int = 10
    mail_imap_host: str = "carbonio.devitalia.it"
    mail_imap_port: int = 993
    mail_username: str = ""
    mail_password: str = ""
    senders_yaml_path: str = "config/senders.yaml"
    mail_state_db_path: str = "data/mail_state.db"
    comet_base_url: str = "https://www.gruppocomet.it"
    comet_login_path: str = "/login?bl=ref"
    comet_ddt_path: str = "/area-riservata/ddt-fatture"
    comet_username: str = ""
    comet_password: str = ""
    comet_supplier_code: str = ""
    comet_download_dir: str = "data/downloads"
    comet_headless: bool = True
    intranet_api_url: str = ""
    intranet_api_token: str = ""
    intranet_send_pdf_base64: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
