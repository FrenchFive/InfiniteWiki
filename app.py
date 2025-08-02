import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import uuid
import datetime
import dotenv
import os

dotenv.load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


app = Flask(__name__)

def generate_token(word):
    word = word.lower().strip().replace(" ", "")  # Normalize the word for token generation
    
    if not word.isalnum():
        return -1  # Invalid token if the word contains non-alphanumeric characters
    
    """Generate a unique token based on the word."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

def gen_links(text):
    paragraph = ""
    for word in text.split():
        token = generate_token(word)
        if token == -1:
            paragraph += word
        else:
            add_article(token, word)  # Add the article to the database
            paragraph += f"<a href='/article/{token}'>{word}</a> "
        # Further processing with the valid token

        print(f"Generated token for '{word}': {token}")

    return paragraph

def init_db():
    if os.path.exists('wiki.db'):
        return

    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                name TEXT UNIQUE,
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
    with open('default_article.txt', 'r') as file:
        text = file.read()

    conn.execute('''
        INSERT OR IGNORE INTO articles (token, name, info_text, discovered_by, discovery_time)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, name, text, "Lau&Five", "TODAY"))
    conn.commit()

    conn.close()

def add_article(token, name):
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()

    # Check if the article already exists
    cursor.execute('SELECT * FROM articles WHERE token = ?', (token,))
    existing_article = cursor.fetchone()

    if existing_article:
        conn.close()
        return 0
    else:
        # Insert the new article into the database
        cursor.execute('''
            INSERT OR IGNORE INTO articles (token, name)
            VALUES (?, ?)
        ''', (token, name))

        conn.commit()
        conn.close()
        return 1

def gen_article(token, name, user):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.create(
        model="gpt-4.1",
        input=[
            {
                "role": "system",
                "content": "You are an expert in creating detailed articles for a wiki (at least 500 words). Only output the article text without any additional commentary."
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
        WHERE token = ?
    ''', (response.output_text, user, datetime.datetime.now(), token))

    conn.commit()
    conn.close()
    return response.output_text

@app.route('/')
def index():
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE name = ?', ("Infinite Wiki",))
    article = cursor.fetchone()
    conn.close()

    info_text = gen_links(article[3])
    return render_template('index.html', wiki_title=article[2], wiki_content=info_text)


@app.route('/article/<token>')
def article(token):
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE token = ?', (token,))
    article = cursor.fetchone()
    conn.close()

    if article:
        token = article[1]
        name = article[2]
        info_text = article[3]

        if len(info_text) == 0:
            info_text = gen_article(token, name, "user")  # Generate article if it doesn't exist

        info_text = gen_links(info_text)
        return render_template('index.html', wiki_title=name, wiki_article=info_text)
    else:
        return "Article not found + ", 404


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
