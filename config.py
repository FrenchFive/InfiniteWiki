import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration for performance optimization."""
    
    # Database settings
    DATABASE_PATH = 'wiki.db'
    DATABASE_TIMEOUT = 30
    DATABASE_CHECK_SAME_THREAD = False
    
    # Cache settings
    CACHE_DURATION = 300  # 5 minutes
    CACHE_MAX_SIZE = 1000
    
    # OpenAI settings
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = "gpt-5-nano"
    OPENAI_TIMEOUT = 30
    
    # Performance settings
    BATCH_SIZE = 100
    MAX_WORKERS = 4
    THREAD_POOL_SIZE = 10
    
    # Article generation settings
    ARTICLE_MIN_WORDS = 300
    ARTICLE_MAX_WORDS = 400
    ARTICLE_SECTIONS = 3
    
    # Link generation settings
    LINK_BATCH_SIZE = 50
    LINK_CACHE_SIZE = 500
    
    # Server settings
    HOST = '0.0.0.0'
    PORT = 5000
    DEBUG = False
    
    # Logging
    LOG_LEVEL = 'INFO'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    
    # Rate limiting
    RATE_LIMIT_PER_MINUTE = 60
    RATE_LIMIT_PER_HOUR = 1000
