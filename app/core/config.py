from pydantic_settings import BaseSettings
import dotenv
import os

dotenv.load_dotenv()

class Settings(BaseSettings):
    DEEPGRAM_API_KEY: str
    OPENAI_API_KEY: str
    YOUTUBE_API_KEY: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    UPLOAD_FOLDER: str = "uploads"

    class Config:
        env_file = ".env"


settings = Settings(
    DEEPGRAM_API_KEY=os.getenv("DEEPGRAM_API_KEY"),
    OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
    YOUTUBE_API_KEY=os.getenv("YOUTUBE_API_KEY"),
    SUPABASE_URL=os.getenv("SUPABASE_URL"),
    SUPABASE_KEY=os.getenv("SUPABASE_KEY"),
)