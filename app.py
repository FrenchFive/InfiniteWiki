import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import uuid
import datetime
import dotenv

dotenv.load_dotenv()


app = Flask(__name__)

def generate_token(word):
    word = word.lower().strip()
    
    if not word.isalnum():
        return -1  # Invalid token if the word contains non-alphanumeric characters
    
    """Generate a unique token based on the word."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

def gen_article(text):
    paragraph = ""
    for word in text.split():
        token = generate_token(word)
        if token == -1:
            paragraph += word
        else:
            paragraph += f"<a href='/article/{token}'>{word}</a> "
        # Further processing with the valid token

        print(f"Generated token for '{word}': {token}")

    return paragraph

def init_db():
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE,
                name TEXT UNIQUE,
                info_text TEXT,
                num_visits INTEGER,
                discovered_by TEXT,
                discovery_time TEXT
            )
    ''')
    conn.commit()
    conn.close()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/article/<token>')
def article(token):
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE token = ?', (token,))
    article = cursor.fetchone()
    conn.close()

    if article:
        info_text = article[3]
        
        return render_template('article.html', article=article)
    else:
        return "Article not found + ", 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
