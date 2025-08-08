import sqlite3
import token
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

# Load environment
dotenv.load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize Flask app
app = Flask(__name__)

# Global NLP model (load once)
NLP = spacy.load("en_core_web_sm")

# Thread-local storage for database connections
thread_local = threading.local()

# Cache for frequently accessed data
CACHE_DURATION = 300  # 5 minutes
cache = {}
cache_lock = threading.Lock()

def get_db_connection():
    """Get thread-local database connection."""
    if not hasattr(thread_local, 'connection'):
        thread_local.connection = sqlite3.connect('wiki.db')
        thread_local.connection.row_factory = sqlite3.Row
    return thread_local.connection

def close_db_connection():
    """Close thread-local database connection."""
    if hasattr(thread_local, 'connection'):
        thread_local.connection.close()
        delattr(thread_local, 'connection')

def cache_get(key):
    """Get value from cache."""
    with cache_lock:
        if key in cache:
            timestamp, value = cache[key]
            if time.time() - timestamp < CACHE_DURATION:
                return value
            else:
                del cache[key]
    return None

def cache_set(key, value):
    """Set value in cache."""
    with cache_lock:
        cache[key] = (time.time(), value)

def current_user():
    """Get current user from request parameters."""
    u = (request.args.get('u') or '').strip()
    return u if u else 'user'

def generate_token(word):
    """Generate UUID token for a word."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

@lru_cache(maxsize=1000)
def clean_word(word):
    """Clean and normalize a word for processing."""
    # Remove HTML tags
    word = re.sub(r'<[^>]+>', '', word)
    # Remove special characters and convert to lowercase
    word = re.sub(r'[^a-z0-9]', '', word.lower())
    return word

def batch_process_words(words, batch_size=100):
    """Process words in batches for better performance."""
    results = []
    for i in range(0, len(words), batch_size):
        batch = words[i:i + batch_size]
        results.extend(process_word_batch(batch))
    return results

def process_word_batch(words):
    """Process a batch of words efficiently."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Clean all words at once
    cleaned_words = [clean_word(word) for word in words]
    cleaned_words = [w for w in cleaned_words if w]
    
    if not cleaned_words:
        return []
    
    # Use a single query to check all words
    placeholders = ','.join(['?' for _ in cleaned_words])
    cursor.execute(f'SELECT name, token FROM articles WHERE name IN ({placeholders})', cleaned_words)
    existing = {row['name']: row['token'] for row in cursor.fetchall()}
    
    # Find missing words
    missing_words = [word for word in cleaned_words if word not in existing]
    
    # Generate tokens for missing words
    new_tokens = {word: generate_token(word) for word in missing_words}
    
    # Insert new words in batch
    if new_tokens:
        insert_data = [(token, word, 0) for word, token in new_tokens.items()]
        cursor.executemany('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', insert_data)
        conn.commit()
    
    # Combine existing and new tokens
    all_tokens = {**existing, **new_tokens}
    
    return [(word, all_tokens.get(clean_word(word), None)) for word in words]

def generate_links_optimized(text, user):
    """Optimized link generation with batch processing."""
    # Split text into words
    words = text.split()
    
    # Process words in batches
    word_token_pairs = batch_process_words(words)
    
    # Generate links efficiently
    linkenized_words = []
    for original_word, token in word_token_pairs:
        if token:
            q_user = urllib.parse.quote(user)
            linkenized_words.append(f'<a href="/article/{token}?u={q_user}">{original_word}</a>')
        else:
            linkenized_words.append(original_word)
    
    return ' '.join(linkenized_words)

def get_user_recent(user, limit=10):
    """Get user's recent discoveries with caching."""
    cache_key = f"user_recent_{user}_{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    conn = get_db_connection()
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
    
    cache_set(cache_key, result)
    return result

def get_user_discovery_count(user):
    """Get user's discovery count with caching."""
    cache_key = f"user_count_{user}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    conn = get_db_connection()
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
    
    cache_set(cache_key, count)
    return count

def get_stats():
    """Get community stats with caching."""
    cached = cache_get("community_stats")
    if cached:
        return cached
    
    conn = get_db_connection()
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
    
    cache_set("community_stats", stats)
    return stats

def get_article_discovery_info(token):
    """Get article discovery info with caching."""
    cache_key = f"article_info_{token}"
    cached = cache_get(cache_key)
    if cached:
        return cached
    
    conn = get_db_connection()
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
    
    cache_set(cache_key, result)
    return result

def increment_article_visits(token):
    """Increment article visit count."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE articles SET num_visits = num_visits + 1 WHERE token = ? AND pointer = 0', (token,))
    conn.commit()
    
    # Invalidate cache
    cache_key = f"article_info_{token}"
    with cache_lock:
        if cache_key in cache:
            del cache[cache_key]

def generate_article_async(token, name, user):
    """Generate article asynchronously for better performance."""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    
    # Optimized prompt for faster generation
    response = client.responses.create(
        model="gpt-5-nano",
        input=[
            {
                "role": "system",
                "content": "Create a concise but informative wiki article (300-400 words) about the given topic. Use clear, engaging language and include 2-3 main sections. Start with an introduction and use HTML formatting (h2 for sections, p for paragraphs). No external links or references."
            },
            {
                "role": "user",
                "content": f"Write a wiki article about {name}."
            }
        ],
    )
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Only update the article content and visit count (discoverer/time already set)
    cursor.execute('''
        UPDATE articles
        SET
            info_text = ?,
            num_visits = 1
        WHERE token = ? AND pointer = 0
          AND (info_text = '' OR info_text IS NULL)
    ''', (response.output_text, token))
    
    # If article already existed, just increment visits
    if cursor.rowcount == 0:
        cursor.execute('''
            UPDATE articles
            SET num_visits = num_visits + 1
            WHERE token = ? AND pointer = 0
        ''', (token,))
    
    conn.commit()
    
    # Invalidate relevant caches
    with cache_lock:
        cache_keys_to_remove = [k for k in cache.keys() if k.startswith(('user_recent_', 'user_count_', 'community_stats'))]
        for key in cache_keys_to_remove:
            del cache[key]
    
    return response.output_text

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
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (1,))
    article = cursor.fetchone()
    
    user = current_user()
    info_text = generate_links_optimized(article["info_text"], user)
    
    # Increment visits and get updated info
    increment_article_visits(article["token"])
    discovery_info = get_article_discovery_info(article["token"])
    
    return render_template(
        'index.html',
        wiki_title=article["name"],
        wiki_content=info_text,
        stats=get_stats(),
        user_recent=get_user_recent(user),
        current_user=user,
        discovery_info=discovery_info,
        user_discovery_count=get_user_discovery_count(user)
    )

@app.route('/article/<token>')
def article(token):
    """Article page route."""
    user = current_user()
    conn = get_db_connection()
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
        cache_key = f"article_info_{token}"
        with cache_lock:
            if cache_key in cache:
                del cache[cache_key]
    
    # Increment visits and get updated info
    increment_article_visits(token)
    discovery_info = get_article_discovery_info(token)
    
    if not needs_generation:
        # Render immediately
        links = generate_links_optimized(info_text, user)
        return render_template(
            'index.html',
            wiki_title=name,
            wiki_content=links,
            stats=get_stats(),
            user_recent=get_user_recent(user),
            current_user=user,
            article_token=token,
            needs_generation=False,
            discovery_info=discovery_info,
            user_discovery_count=get_user_discovery_count(user)
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
        stats=get_stats(),
        user_recent=get_user_recent(user),
        current_user=user,
        article_token=token,
        needs_generation=True,
        discovery_info=discovery_info,
        user_discovery_count=get_user_discovery_count(user)
    )

@app.get('/api/user_recent')
def api_user_recent():
    """API endpoint for user's recent discoveries."""
    user = current_user()
    return jsonify({
        "user": user,
        "recent": get_user_recent(user)
    })

@app.get('/api/stats')
def api_stats():
    """API endpoint for community stats."""
    return jsonify(get_stats())

@app.get('/api/article/<token>')
def api_article_generate(token):
    """API endpoint for article generation."""
    user = current_user()
    
    # Fetch the row
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = 0', (token,))
    row = cursor.fetchone()
    
    if not row:
        return jsonify({"ok": False, "error": "not_found"}), 404
    
    name = row["name"]
    info_text = row["info_text"] or ""
    was_empty = (info_text.strip() == "")
    
    # Generate article if needed
    if was_empty:
        info_text = generate_article_async(token, name, user)
        # For new discoveries, don't increment visits again
        discovery_info = get_article_discovery_info(token)
    else:
        # For existing articles, increment visits
        increment_article_visits(token)
        discovery_info = get_article_discovery_info(token)
    
    # Generate links
    html = generate_links_optimized(info_text, user)
    
    return jsonify({
        "ok": True,
        "title": name,
        "html": html,
        "was_discovery": was_empty,
        "discovery_info": discovery_info,
        "updated_stats": get_stats()
    })

# Request lifecycle hooks
@app.before_request
def before_request():
    """Setup before each request."""
    pass

@app.teardown_request
def teardown_request(exception=None):
    """Cleanup after each request."""
    close_db_connection()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
