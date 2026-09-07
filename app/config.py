class Settings(BaseSettings):
    GOOGLE_API_KEY: str
    DATABASE_URL: str                                  # postgresql+asyncpg://user:pw@host:5432/ssok
    EMBEDDING_MODEL: str = "models/text-embedding-004"
    EMBEDDING_DIM: int = 768