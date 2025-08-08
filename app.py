import sqlite3
import redis
import json
import hashlib
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import uuid
import datetime
import dotenv
import os
import re
import spacy
import multiprocessing
import urllib.parse
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from typing import Dict, List, Optional, Tuple
import logging

# Load environment
dotenv.load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Initialize Flask app
app = Flask(__name__)

# Global NLP model (load once)
NLP = spacy.load("en_core_web_sm")

# Redis connection
redis_client = None

# Database connection pool
db_pool = []
db_pool_lock = threading.Lock()
MAX_DB_CONNECTIONS = 10

# Performance settings
BATCH_SIZE = 200
CACHE_DURATION = 600  # 10 minutes
MAX_WORKERS = 8

# Pre-computed word tokens cache
word_token_cache = {}
word_cache_lock = threading.Lock()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_redis():
    """Initialize Redis connection."""
    global redis_client
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")
        redis_client = None

def get_db_connection():
    """Get database connection from pool."""
    with db_pool_lock:
        if db_pool:
            return db_pool.pop()
        else:
            conn = sqlite3.connect('wiki.db', timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

def return_db_connection(conn):
    """Return database connection to pool."""
    with db_pool_lock:
        if len(db_pool) < MAX_DB_CONNECTIONS:
            db_pool.append(conn)
        else:
            conn.close()

def cache_get(key: str) -> Optional[str]:
    """Get value from Redis cache."""
    if not redis_client:
        return None
    try:
        return redis_client.get(key)
    except Exception as e:
        logger.error(f"Redis get error: {e}")
        return None

def cache_set(key: str, value: str, expire: int = CACHE_DURATION):
    """Set value in Redis cache."""
    if not redis_client:
        return
    try:
        redis_client.setex(key, expire, value)
    except Exception as e:
        logger.error(f"Redis set error: {e}")

def current_user():
    """Get current user from request parameters."""
    u = (request.args.get('u') or '').strip()
    return u if u else 'user'

def generate_token(word: str) -> str:
    """Generate UUID token for a word."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

@lru_cache(maxsize=10000)
def clean_word(word: str) -> str:
    """Clean and normalize a word for processing."""
    # Remove HTML tags
    word = re.sub(r'<[^>]+>', '', word)
    # Remove special characters and convert to lowercase
    word = re.sub(r'[^a-z0-9]', '', word.lower())
    return word

def precompute_word_tokens():
    """Pre-compute tokens for common words."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT name, token FROM articles WHERE pointer = 0')
        existing_words = {row['name']: row['token'] for row in cursor.fetchall()}
        
        with word_cache_lock:
            word_token_cache.update(existing_words)
        
        logger.info(f"Pre-computed {len(existing_words)} word tokens")
    finally:
        return_db_connection(conn)

def batch_process_words_optimized(words: List[str]) -> List[Tuple[str, Optional[str]]]:
    """Process words in batches with optimized caching."""
    if not words:
        return []
    
    # Clean all words at once
    cleaned_words = [clean_word(word) for word in words]
    cleaned_words = [w for w in cleaned_words if w]
    
    if not cleaned_words:
        return [(word, None) for word in words]
    
    # Check cache first
    cached_tokens = {}
    uncached_words = []
    
    for word in cleaned_words:
        with word_cache_lock:
            if word in word_token_cache:
                cached_tokens[word] = word_token_cache[word]
            else:
                uncached_words.append(word)
    
    # Process uncached words in database
    if uncached_words:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            
            # Use a single query to check all words
            placeholders = ','.join(['?' for _ in uncached_words])
            cursor.execute(f'SELECT name, token FROM articles WHERE name IN ({placeholders})', uncached_words)
            existing = {row['name']: row['token'] for row in cursor.fetchall()}
            
            # Generate tokens for missing words
            missing_words = [word for word in uncached_words if word not in existing]
            new_tokens = {word: generate_token(word) for word in missing_words}
            
            # Insert new words in batch
            if new_tokens:
                insert_data = [(token, word, 0) for word, token in new_tokens.items()]
                cursor.executemany('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', insert_data)
                conn.commit()
            
            # Update cache
            with word_cache_lock:
                word_token_cache.update(existing)
                word_token_cache.update(new_tokens)
            
            # Combine all tokens
            all_tokens = {**existing, **new_tokens}
            cached_tokens.update(all_tokens)
            
        finally:
            return_db_connection(conn)
    
    # Map back to original words
    result = []
    for original_word in words:
        cleaned = clean_word(original_word)
        token = cached_tokens.get(cleaned)
        result.append((original_word, token))
    
    return result

def generate_links_optimized(text: str, user: str) -> str:
    """Optimized link generation with batch processing."""
    # Split text into words
    words = text.split()
    
    # Process words in batches
    word_token_pairs = batch_process_words_optimized(words)
    
    # Generate links efficiently
    linkenized_words = []
    for original_word, token in word_token_pairs:
        if token:
            q_user = urllib.parse.quote(user)
            linkenized_words.append(f'<a href="/article/{token}?u={q_user}">{original_word}</a>')
        else:
            linkenized_words.append(original_word)
    
    return ' '.join(linkenized_words)

def get_user_recent_optimized(user: str, limit: int = 10) -> List[Dict]:
    """Get user's recent discoveries with optimized caching."""
    cache_key = f"user_recent_{user}_{limit}"
    cached = cache_get(cache_key)
    if cached:
        return json.loads(cached)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, discovery_time, token
            FROM articles
            WHERE pointer = 0
              AND discovered_by = ?
              AND info_text IS NOT NULL
              AND info_text != ''
            ORDER BY datetime(discovery_time) DESC
            LIMIT ?
        ''', (user, limit))
        
        rows = cursor.fetchall()
        result = [{"name": r["name"], "discovery_time": r["discovery_time"], "token": r["token"]} for r in rows]
        
        cache_set(cache_key, json.dumps(result))
        return result
    finally:
        return_db_connection(conn)

def get_user_discovery_count_optimized(user: str) -> int:
    """Get user's discovery count with optimized caching."""
    cache_key = f"user_count_{user}"
    cached = cache_get(cache_key)
    if cached:
        return int(cached)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM articles
            WHERE pointer = 0
              AND discovered_by = ?
              AND info_text IS NOT NULL
              AND info_text != ''
        ''', (user,))
        
        result = cursor.fetchone()
        count = result[0] if result else 0
        
        cache_set(cache_key, str(count))
        return count
    finally:
        return_db_connection(conn)

def get_stats_optimized() -> Dict:
    """Get community stats with optimized caching."""
    cached = cache_get("community_stats")
    if cached:
        return json.loads(cached)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Get total discovered articles
        cursor.execute('SELECT COUNT(*) as total_articles FROM articles WHERE pointer = 0 AND info_text != ""')
        total_articles = cursor.fetchone()["total_articles"]
        
        # Get total undiscovered articles
        cursor.execute('SELECT COUNT(*) as total_undiscovered FROM articles WHERE pointer = 0 AND info_text = ""')
        total_undiscovered = cursor.fetchone()["total_undiscovered"]
        
        # Get most active user
        cursor.execute('''
            SELECT discovered_by, COUNT(*) AS discoveries 
            FROM articles 
            WHERE discovered_by != "" AND discovered_by IS NOT NULL
            GROUP BY discovered_by 
            ORDER BY discoveries DESC 
            LIMIT 1
        ''')
        most_active_user_row = cursor.fetchone()
        most_active_user = most_active_user_row["discovered_by"] if most_active_user_row else "None"
        
        stats = {
            "total_articles": total_articles,
            "total_undiscovered": total_undiscovered,
            "most_active_user": most_active_user,
        }
        
        cache_set("community_stats", json.dumps(stats))
        return stats
    finally:
        return_db_connection(conn)

def get_article_discovery_info_optimized(token: str) -> Dict:
    """Get article discovery info with optimized caching."""
    cache_key = f"article_info_{token}"
    cached = cache_get(cache_key)
    if cached:
        return json.loads(cached)
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT discovered_by, discovery_time, num_visits FROM articles WHERE token = ? AND pointer = 0', (token,))
        row = cursor.fetchone()
        
        if row:
            # Format the date
            discovery_time = row["discovery_time"]
            if discovery_time:
                try:
                    dt = datetime.datetime.fromisoformat(discovery_time.replace('Z', '+00:00'))
                    formatted_time = dt.strftime("%B %d, %Y at %I:%M %p")
                except:
                    formatted_time = discovery_time
            else:
                formatted_time = None
                
            result = {
                "discovered_by": row["discovered_by"] or None,
                "discovery_time": formatted_time,
                "visits": row["num_visits"] or 0
            }
        else:
            result = {"discovered_by": None, "discovery_time": None, "visits": 0}
        
        cache_set(cache_key, json.dumps(result))
        return result
    finally:
        return_db_connection(conn)

def increment_article_visits_optimized(token: str):
    """Increment article visit count with optimized caching."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('UPDATE articles SET num_visits = num_visits + 1 WHERE token = ? AND pointer = 0', (token,))
        conn.commit()
        
        # Invalidate cache
        cache_key = f"article_info_{token}"
        if redis_client:
            redis_client.delete(cache_key)
    finally:
        return_db_connection(conn)

def generate_article_optimized(token: str, name: str, user: str) -> str:
    """Generate article with optimized performance using GPT-5 NANO."""
    if not OPENAI_API_KEY:
        logger.error("OpenAI API key not found")
        return "Error: OpenAI API key not configured. Please check your .env file."
    
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    # Optimized prompt for faster generation with GPT-5 NANO
    try:
        logger.info(f"Generating article for '{name}' using GPT-4o-mini...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Fast and reliable model
            messages=[
                {
                    "role": "system",
                    "content": "Create a concise wiki article (200-300 words) about the given topic. Use clear language and include 2-3 main sections. Start with an introduction and use HTML formatting (h2 for sections, p for paragraphs). Be brief but informative."
                },
                {
                    "role": "user",
                    "content": f"Write a wiki article about {name}."
                }
            ],
            max_tokens=400,  # Limit tokens for faster generation
            temperature=0.7,
            timeout=15.0  # Increased timeout for reliability
        )
        
        content = response.choices[0].message.content
        logger.info(f"Successfully generated article for '{name}' ({len(content)} characters)")
        
        # Update database
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE articles
                SET
                    info_text = ?,
                    num_visits = 1
                WHERE token = ? AND pointer = 0
                  AND (info_text = '' OR info_text IS NULL)
            ''', (content, token))
            
            if cursor.rowcount == 0:
                cursor.execute('''
                    UPDATE articles
                    SET num_visits = num_visits + 1
                    WHERE token = ? AND pointer = 0
                ''', (token,))
            
            conn.commit()
        finally:
            return_db_connection(conn)
        
        # Invalidate relevant caches
        if redis_client:
            cache_keys_to_remove = [
                f"user_recent_{user}_10",
                f"user_count_{user}",
                "community_stats"
            ]
            for key in cache_keys_to_remove:
                redis_client.delete(key)
        
        return content
        
    except openai.AuthenticationError as e:
        logger.error(f"OpenAI authentication error: {e}")
        return "Error: Invalid OpenAI API key. Please check your API key in the .env file."
    except openai.RateLimitError as e:
        logger.error(f"OpenAI rate limit error: {e}")
        return "Error: Rate limit exceeded. Please try again in a moment."
    except openai.APIError as e:
        logger.error(f"OpenAI API error: {e}")
        return f"Error: OpenAI API issue - {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error generating article: {e}")
        return f"Error generating article: {str(e)}"

def init_db():
    """Initialize database with optimized structure."""
    if os.path.exists('wiki.db'):
        return
    
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    
    # Create optimized table structure
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            name TEXT UNIQUE,
            pointer INTEGER DEFAULT 0,
            info_text TEXT DEFAULT '',
            num_visits INTEGER DEFAULT 0,
            discovered_by TEXT DEFAULT '',
            discovery_time TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create indexes for better performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_pointer ON articles(pointer)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_discovered_by ON articles(discovered_by)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_discovery_time ON articles(discovery_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_name ON articles(name)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_info_text ON articles(info_text)')
    
    conn.commit()
    
    # Initialize with default article
    name = "Infinite Wiki"
    token = generate_token(name)
    with open('default_article.txt', 'r', encoding='utf-8') as file:
        text = file.read()
    
    cursor.execute('''
        INSERT OR IGNORE INTO articles (token, name, info_text, discovered_by, discovery_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, name, text, "Lau&Five", datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

# Flask routes
@app.route('/')
def index():
    """Home page route."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM articles WHERE id = ?', (1,))
        article = cursor.fetchone()
        
        user = current_user()
        info_text = generate_links_optimized(article["info_text"], user)
        
        # Increment visits and get updated info
        increment_article_visits_optimized(article["token"])
        discovery_info = get_article_discovery_info_optimized(article["token"])
        
        return render_template(
            'index.html',
            wiki_title=article["name"],
            wiki_content=info_text,
            stats=get_stats_optimized(),
            user_recent=get_user_recent_optimized(user),
            current_user=user,
            discovery_info=discovery_info,
            user_discovery_count=get_user_discovery_count_optimized(user)
        )
    finally:
        return_db_connection(conn)

@app.route('/article/<token>')
def article(token):
    """Article page route."""
    user = current_user()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = ?', (token, 0))
        row = cursor.fetchone()
        
        if not row:
            return "Article not found", 404
        
        name = row["name"]
        info_text = (row["info_text"] or "")
        needs_generation = (info_text.strip() == "")
        
        # For new discoveries, set the discoverer and time immediately
        if needs_generation:
            cursor.execute('''
                UPDATE articles
                SET 
                    discovered_by = CASE
                        WHEN (discovered_by = '' OR discovered_by IS NULL) THEN ?
                        ELSE discovered_by
                    END,
                    discovery_time = CASE
                        WHEN (discovery_time = '' OR discovery_time IS NULL) THEN ?
                        ELSE discovery_time
                    END
                WHERE token = ? AND pointer = 0
            ''', (user, datetime.datetime.now().isoformat(), token))
            conn.commit()
            
            # Invalidate article info cache since we just updated discoverer/time
            if redis_client:
                redis_client.delete(f"article_info_{token}")
        
        # Increment visits and get updated info
        increment_article_visits_optimized(token)
        discovery_info = get_article_discovery_info_optimized(token)
        
        if not needs_generation:
            # Render immediately
            links = generate_links_optimized(info_text, user)
            return render_template(
                'index.html',
                wiki_title=name,
                wiki_content=links,
                stats=get_stats_optimized(),
                user_recent=get_user_recent_optimized(user),
                current_user=user,
                article_token=token,
                needs_generation=False,
                discovery_info=discovery_info,
                user_discovery_count=get_user_discovery_count_optimized(user)
            )
        
        # Render shell with loader
        loader_shell = """
          <div id="articleLoader" class="discovery-card" aria-live="polite">
            <div class="discovery-card__content">
              <div class="discovery-card__icon" aria-hidden="true">💡</div>
              <h2 class="discovery-card__title">New discovery by <span id="discoveryUser"></span>!</h2>
              <p class="discovery-card__date" id="discoveryDate"></p>
              <div class="discovery-card__status">
                <p class="discovery-card__text" id="loadingStatus">
                  Searching for the article
                  <span class="dots"><span>.</span><span>.</span><span>.</span></span>
                </p>
              </div>
            </div>
          </div>
          <div id="articleContent" hidden></div>
        """
        
        return render_template(
            'index.html',
            wiki_title=name,
            wiki_content=loader_shell,
            stats=get_stats_optimized(),
            user_recent=get_user_recent_optimized(user),
            current_user=user,
            article_token=token,
            needs_generation=True,
            discovery_info=discovery_info,
            user_discovery_count=get_user_discovery_count_optimized(user)
        )
    finally:
        return_db_connection(conn)

@app.get('/api/user_recent')
def api_user_recent():
    """API endpoint for user's recent discoveries."""
    user = current_user()
    return jsonify({
        "user": user,
        "recent": get_user_recent_optimized(user)
    })

@app.get('/api/stats')
def api_stats():
    """API endpoint for community stats."""
    return jsonify(get_stats_optimized())

@app.get('/api/search')
def api_search():
    """API endpoint for searching discovered articles."""
    query = request.args.get('q', '').strip().lower()
    if not query:
        return jsonify({"results": []})
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Search for discovered articles that match the query
        cursor.execute('''
            SELECT name, token
            FROM articles
            WHERE pointer = 0 
              AND info_text != '' 
              AND info_text IS NOT NULL
              AND LOWER(name) LIKE ?
            ORDER BY name
            LIMIT 10
        ''', (f'%{query}%',))
        
        results = [{"name": row["name"], "token": row["token"]} for row in cursor.fetchall()]
        return jsonify({"results": results})
    finally:
        return_db_connection(conn)

@app.get('/api/article/<token>')
def api_article_generate(token):
    """API endpoint for article generation."""
    user = current_user()
    
    # Fetch the row
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = 0', (token,))
        row = cursor.fetchone()
        
        if not row:
            # Create the article if it doesn't exist
            name = token  # Use token as name for now
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO articles (token, name, pointer, discovered_by, discovery_time)
                    VALUES (?, ?, 0, ?, ?)
                ''', (token, name, user, datetime.datetime.now().isoformat()))
                conn.commit()
                
                # Fetch the newly created row
                cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = 0', (token,))
                row = cursor.fetchone()
                
                if not row:
                    # Try to find by name instead
                    cursor.execute('SELECT * FROM articles WHERE name = ? AND pointer = 0', (name,))
                    row = cursor.fetchone()
                    
                    if not row:
                        return jsonify({"ok": False, "error": "failed_to_create"}), 500
            except Exception as e:
                logger.error(f"Error creating article: {e}")
                # Try to find existing article by name
                cursor.execute('SELECT * FROM articles WHERE name = ? AND pointer = 0', (name,))
                row = cursor.fetchone()
                
                if not row:
                    return jsonify({"ok": False, "error": "failed_to_create"}), 500
        
        name = row["name"]
        info_text = row["info_text"] or ""
        was_empty = (info_text.strip() == "")
        
        # Generate article if needed
        if was_empty:
            info_text = generate_article_optimized(token, name, user)
            # For new discoveries, don't increment visits again
            discovery_info = get_article_discovery_info_optimized(token)
        else:
            # For existing articles, increment visits
            increment_article_visits_optimized(token)
            discovery_info = get_article_discovery_info_optimized(token)
        
        # Generate links
        html = generate_links_optimized(info_text, user)
        
        return jsonify({
            "ok": True,
            "title": name,
            "html": html,
            "was_discovery": was_empty,
            "discovery_info": discovery_info,
            "updated_stats": get_stats_optimized()
        })
    finally:
        return_db_connection(conn)

# Request lifecycle hooks
@app.before_request
def before_request():
    """Setup before each request."""
    pass

@app.teardown_request
def teardown_request(exception=None):
    """Cleanup after each request."""
    pass

def startup():
    """Initialize application on startup."""
    logger.info("🚀 Starting InfiniteWiki with GPT-4o-mini...")
    init_redis()
    precompute_word_tokens()
    logger.info("✅ Application startup complete - Ready to generate articles!")
    logger.info("📊 Performance optimizations: Redis caching, connection pooling, pre-computed tokens")

if __name__ == '__main__':
    logger.info("🎯 InfiniteWiki - Single File Optimized Version")
    logger.info("🔧 Using GPT-4o-mini with OpenAI 1.99.3")
    init_db()
    startup()
    app.run(debug=True, host='0.0.0.0', port=5000)
