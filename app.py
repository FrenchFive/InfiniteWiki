import sqlite3
import token
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import uuid
import datetime
import dotenv
import os
import re
import tqdm
import spacy
import multiprocessing
import urllib.parse


NLP = spacy.load("en_core_web_sm")

dotenv.load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


app = Flask(__name__)

def current_user():
    u = (request.args.get('u') or '').strip()
    return u if u else 'user'

def get_user_recent(user, limit=10):
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        '''
        SELECT name
        FROM articles
        WHERE pointer = 0
          AND discovered_by = ?
          AND info_text IS NOT NULL
          AND info_text != ''
        ORDER BY datetime(discovery_time) DESC
        LIMIT ?
        ''',
        (user, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [r["name"] for r in rows]


def check_tokens(words):
    conn = sqlite3.connect('wiki.db')
    li_tokenized = []
    li_unknown = []
    cursor = conn.cursor()
    for word in words:
        cursor.execute('SELECT token FROM articles WHERE name = ?', (word,))
        data = cursor.fetchone()
        if data:
            li_tokenized.append(word)
        else:
            li_unknown.append(word)

    conn.close()

    return li_unknown

def _process_chunk(chunk):
    """Process a chunk of words and return rows and mappings."""
    rows = []
    mapping = {}
    for word in chunk:
        pointer_token, pointer = check_pointer(word)
        if pointer_token == 0:
            token = generate_token(word)
            mapping[word] = token
            rows.append((token, word, 0))
        else:
            mapping[word] = pointer_token
            rows.append((pointer_token, pointer, 0))
            rows.append((pointer_token, word, 1))
    return rows, mapping


def _chunkify(lst, n):
    """Split *lst* into *n* nearly equal chunks."""
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m):(i + 1) * k + min(i + 1, m)] for i in range(n)]


def tokenize(words):
    """Tokenize the words and add them to the database."""
    if not words:
        return

    # Determine number of chunks (4 or 5 when possible)
    num_chunks = 5 if len(words) >= 5 else (4 if len(words) >= 4 else len(words))
    chunks = _chunkify(words, num_chunks)

    with multiprocessing.Pool(processes=num_chunks) as pool:
        chunk_results = pool.map(_process_chunk, chunks)

    rows = []
    token_map = {}
    for chunk_rows, mapping in chunk_results:
        rows.extend(chunk_rows)
        token_map.update(mapping)

    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.executemany('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', rows)
    conn.commit()
    conn.close()
    return token_map

def linkenize(words, user):  
    html = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    
    linkenized_words = []
    for word in words:
        word_clean = word.strip().lower()
        word_clean = re.sub(html, '', word_clean)
        word_clean = re.sub(r'[^a-z0-9]', '', word_clean)

        if len(word_clean) == 0:
            linkenized_words.append(word)
        else:
            cursor.execute('SELECT token FROM articles WHERE name = ?', (word_clean,))
            data = cursor.fetchone()
            if data:
                tok = data[0]
                q_user = urllib.parse.quote(user)
                linkenized_words.append(f"<a href='/article/{tok}?u={q_user}'>{word}</a> ")
            else:
                linkenized_words.append(word)

    conn.close()
    return linkenized_words


def generate_token(word):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

def generate_links(text, user):   # <-- add user
    word_list = text.split()
    html = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    word_list_html = [re.sub(html, '', word) for word in word_list]

    word_list_cleaned = []
    for word in word_list_html:
        word = word.strip().lower()
        word = re.sub(r'[^a-z0-9]', '', word)
        if len(word) > 0:
            word_list_cleaned.append(word)
    cleaned_list = list(set(word_list_cleaned))
    li_unknown = check_tokens(cleaned_list)
    print(f"Tokenized words : {len(cleaned_list) - len(li_unknown)}")
    print(f"Unknown words : {len(li_unknown)}")

    tokenize(li_unknown)

    link_list = linkenize(word_list, user)  # <-- pass user
    paragraph = " ".join(link_list)
    return paragraph


def init_db():
    if os.path.exists('wiki.db'):
        return

    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT,
                name TEXT UNIQUE,
                pointer INTEGER DEFAULT 0,
                info_text TEXT DEFAULT '',
                num_visits INTEGER DEFAULT 0,
                discovered_by TEXT DEFAULT '',
                discovery_time TEXT DEFAULT ''
            )
    ''')
    conn.commit()
    

    # Inintialize the database with a default article
    name = "Infinite Wiki"
    token = generate_token(name)
    with open('default_article.txt', 'r', encoding='utf-8') as file:
        text = file.read()

    conn.execute('''
        INSERT OR IGNORE INTO articles (token, name, info_text, discovered_by, discovery_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, name, text, "Lau&Five", "TODAY"))
    conn.commit()

    conn.close()

def generate_article(token, name, user):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.create(
        model="gpt-5-nano",
        input=[
            {
                "role": "system",
                "content": "You are an expert in creating detailed articles for a wiki (at least 500 words). Only output the article text without any additional commentary. Be creative and dont hesitate to invent new information if necessary."
            },
            {
                "role": "system",
                "content": "Use HTML formatting to structure the article. Do not include any links or references to external sources. No Javascript or CSS code only HTML. Do not define the html no <head> or <body> tags nor <html> or <!DOCTYPE html>, maximum size should be h2. Do not include the title of the article, start with the introduction."
            },
            {
                "role": "user",
                "content": f"Create a detailed article about {name}."
            }
        ],
    )

    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()

    # Write the article text and bump visits.
    # Mark discovery ONLY now (first generation), and NEVER earlier.
    cursor.execute('''
        UPDATE articles
        SET
            info_text = ?,
            num_visits = num_visits + 1,
            -- Only stamp discoverer if this is the first time the article is generated
            discovered_by = CASE
                WHEN (discovered_by = '' OR discovered_by IS NULL) THEN ?
                ELSE discovered_by
            END,
            discovery_time = CASE
                WHEN (discovery_time = '' OR discovery_time IS NULL) THEN ?
                ELSE discovery_time
            END
        WHERE token = ? AND pointer = 0
          AND (info_text = '' OR info_text IS NULL)  -- ensure it's truly first generation
    ''', (response.output_text, user, datetime.datetime.now().isoformat(), token))

    # If the article already existed (someone discovered before), still bump visits but don't take credit
    if cursor.rowcount == 0:
        cursor.execute('''
            UPDATE articles
            SET num_visits = num_visits + 1
            WHERE token = ? AND pointer = 0
        ''', (token,))

    conn.commit()
    conn.close()
    return response.output_text


def check_pointer(word):
    doc = NLP(word)
    for token in doc:
        pointer = token.lemma_.lower()
    
    pointer = re.sub(r'[^a-z0-9]', '', pointer)  # Clean the pointer word
    if word == pointer:
        return 0, ""
    
    
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    # Check if the pointer already exists in the database
    cursor.execute('SELECT token FROM articles WHERE name = ?', (pointer,))
    existing_pointer = cursor.fetchone()
    if existing_pointer:
        pointer_token = existing_pointer[0]
    else:
        pointer_token = generate_token(pointer)  # Generate a token for the pointer word

    conn.commit()
    conn.close()
    return pointer_token, pointer

def get_stats():
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as total_articles FROM articles WHERE pointer = 0 and info_text != ""')
    total_articles = cursor.fetchone()["total_articles"]

    cursor.execute('SELECT COUNT(*) as total_undiscovered FROM articles WHERE info_text == "" and pointer = 0')
    total_undiscovered = cursor.fetchone()["total_undiscovered"]

    cursor.execute('SELECT discovered_by, COUNT(*) AS discoveries FROM articles WHERE discovered_by != "" GROUP BY discovered_by ORDER BY discoveries DESC LIMIT 1')
    most_active_user = cursor.fetchone()

    stat = {
        "total_articles": total_articles,
        "total_undiscovered": total_undiscovered,
        "most_active_user": most_active_user["discovered_by"] if most_active_user else "None",
    }

    return stat

@app.route('/')
def index():
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (1,))
    article = cursor.fetchone()
    conn.close()

    user = current_user()
    info_text = generate_links(article["info_text"], user)

    return render_template(
        'index.html',
        wiki_title=article["name"],
        wiki_content=info_text,
        stats=get_stats(),
        user_recent=get_user_recent(user),
        current_user=user
    )


@app.route('/article/<token>')
def article(token):
    user = current_user()
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = ?', (token, 0))
    article = cursor.fetchone()
    conn.close()

    if article:
        token = article["token"]
        name = article["name"]
        info_text = article["info_text"]

        if len(info_text) == 0:
            info_text = generate_article(token, name, user)

        links = generate_links(info_text, user)
        return render_template(
            'index.html',
            wiki_title=name,
            wiki_content=links,
            stats=get_stats(),
            user_recent=get_user_recent(user),
            current_user=user
        )
    else:
        return "Article not found + ", 404

@app.get('/api/user_recent')
def api_user_recent():
    user = current_user()  # reads ?u=...
    return jsonify({
        "user": user,
        "recent": get_user_recent(user)
    })



if __name__ == '__main__':
    init_db()
    app.run(debug=True)
