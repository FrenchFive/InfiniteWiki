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

NLP = spacy.load("en_core_web_sm")

dotenv.load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


app = Flask(__name__)

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

def tokenize(words):
    """Tokenize the words and add them to the database."""
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    
    for word in tqdm.tqdm(words, desc="Tokenizing words"):
        pointer_token, pointer = check_pointer(word)  # Make sure the word doesnt need to point to another word
        if pointer_token == 0:
            token = generate_token(word)  # Generate a token for the word
            cursor.execute('INSERT OR IGNORE INTO articles (token, name) VALUES (?, ?)', (token, word))
            conn.commit()
        else:
            cursor.execute('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', (pointer_token, pointer, 0))
            conn.commit()
            cursor.execute('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', (pointer_token, word, 1))
            conn.commit()
            
    
    conn.commit()
    conn.close()

def linkenize(words):
    html = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    
    linkenized_words = []
    for word in words:
        word_clean = word.strip().lower()
        word_clean = re.sub(html, '', word_clean)  # Remove HTML tags
        word_clean = re.sub(r'[^a-z0-9]', '', word_clean)  # Clean the word

        if len(word_clean) == 0:
            linkenized_words.append(word)
        else:
            cursor.execute('SELECT token FROM articles WHERE name = ?', (word_clean,))
            data = cursor.fetchone()
            if data:
                token = data[0]
                linkenized_words.append(f"<a href='/article/{token}'>{word}</a> ")
            else:
                # If the word is not found, keep it as is
                linkenized_words.append(word)

    conn.close()
    return linkenized_words

def generate_token(word):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

def generate_links(text):
    word_list = text.split()

    html = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    word_list_html = [re.sub(html, '', word) for word in word_list]  # Remove HTML tags


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

    link_list = linkenize(word_list)

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
        model="gpt-4.1",
        input=[
            {
                "role": "system",
                "content": "You are an expert in creating detailed articles for a wiki (at least 500 words). Only output the article text without any additional commentary. Be creative and dont hesitate to invent new information if necessary."
            },
            {
                "role": "system",
                "content": "Use HTML formatting to structure the article. Do not include any links or references to external sources. Do not define the html no <head> or <body> tags nor <html> or <!DOCTYPE html>, maximum size should be h2. Do not include the title of the article, start with the introduction."
            },
            {
                "role": "user",
                "content": f"Create a detailed article about {name}."
            }
        ],
    )

    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE articles
        SET info_text = ?, num_visits = num_visits + 1, discovered_by = ?, discovery_time = ?
        WHERE token = ? and pointer = 0
    ''', (response.output_text, user, datetime.datetime.now(), token))

    conn.commit()
    conn.close()
    return response.output_text

def check_pointer(word):
    doc = NLP(word)
    for token in doc:
        if token.is_oov == True and token.lemma_ == word:
            pointer = "<UNK>"
        else:
            pointer = token.lemma_.lower()

    if pointer == "<UNK>":
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        response = client.responses.create(
            model="gpt-4.1-nano-2025-04-14",
            input=[
                {
                    "role": "system",
                    "content": "If the word is plural, output the singular word. If the word is a verb, output the unconjugated form. ONLY OUTPUT 1 WORD."
                },
                {
                    "role": "user",
                    "content": f"{word}"
                }
            ]
        )

        pointer = response.output_text.strip().lower()
    
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
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (1,))
    article = cursor.fetchone()
    conn.close()

    info_text = generate_links(article["info_text"])
    return render_template('index.html', wiki_title=article["name"], wiki_content=info_text, stats=get_stats())


@app.route('/article/<token>')
def article(token):
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE token = ? AND pointer = ?', (token, 0))
    article = cursor.fetchone()
    conn.close()

    if article:
        token = article["token"]
        name = article["name"]
        info_text = article["info_text"]

        if len(info_text) == 0:
            info_text = generate_article(token, name, "user")  # Generate article if it doesn't exist

        links = generate_links(info_text)
        return render_template('index.html', wiki_title=name, wiki_content=links, stats=get_stats())
    else:
        return "Article not found + ", 404


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
