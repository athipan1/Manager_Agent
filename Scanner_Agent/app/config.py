from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Scoring weights
    QUALITY_SCORE_WEIGHT: float = 0.40
    GROWTH_SCORE_WEIGHT: float = 0.35
    VALUATION_SCORE_WEIGHT: float = 0.25

    # Alpaca API
    APCA_API_KEY_ID: str = "YOUR_API_KEY"
    APCA_API_SECRET_KEY: str = "YOUR_SECRET_KEY"
    APCA_API_BASE_URL: str = "https://paper-api.alpaca.markets"


settings = Settings()
