import sqlite3
import token
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import uuid
import datetime
import dotenv
import os
import re

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
    
    for word in words:
        pointer_token = check_pointer(word)  # Make sure the word doesnt need to point to another word
        if pointer_token == 0:
            token = generate_token(word)  # Generate a token for the word
            cursor.execute('INSERT OR IGNORE INTO articles (token, name) VALUES (?, ?)', (token, word))
        else:
            cursor.execute('INSERT OR IGNORE INTO articles (token, name, pointer) VALUES (?, ?, ?)', (pointer_token, word, 1))
            
    
    conn.commit()
    conn.close()

def linkenize(words):
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    
    linkenized_words = []
    for word in words:
        word = word.strip().lower()
        word = re.sub(r'[^a-z0-9]', '', word)  # Clean the word
        if len(word) > 0:
            linkenized_words.append(word)
        else:
            cursor.execute('SELECT token FROM articles WHERE name = ?', (word,))
            data = cursor.fetchone()
            if data:
                token = data[0]
                linkenized_words.append(f"<a href='/article/{token}'>{word}</a> ")
            else:
                # If the word is not found, keep it as is
                linkenized_words.append(word)

    conn.close()
    return linkenized_words

def check_token(name):
    """Check if the token already exists in the database."""
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('SELECT token, pointer FROM articles WHERE name = ?', (name,))
    data = cursor.fetchone()
    if data:
        token = data[0]
        pointer = data[1]
        if token == 0:
            return pointer  # Return the pointer if the token is 0
        return token  # Return the existing token
    else:
        pointer = check_pointer(name)  # Check if a pointer exists for the name
        if pointer == 0:
            token = generate_token(name)
        else:
            token = pointer  # Use the pointer as the token
    conn.close()

    return token

def generate_token(word):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

def gen_links(text):
    word_list = text.split()


    word_list_cleaned = []
    for word in word_list:
        word = word.strip().lower()
        word = re.sub(r'[^a-z0-9]', '', word)
        if len(word) > 0:
            word_list_cleaned.append(word)
    cleaned_list = list(set(word_list_cleaned))
    li_unknown = check_tokens(cleaned_list)

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
                token TEXT UNIQUE,
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

def check_pointer(word):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    response = client.chat.completions.create(
        model="gpt-4.1-nano-2025-04-14",
        messages=[
            {
                "role": "system",
                "content": "Output the word if it is the most relevant, otherwise output the most relevant word. 'is' and 'are' should point to 'be', referenced should point to 'reference' etc. ONLY output a SINGLE WORD."
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
        return 0
    
    
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    # Check if the pointer already exists in the database
    cursor.execute('SELECT token FROM articles WHERE name = ?', (pointer,))
    existing_pointer = cursor.fetchone()
    if existing_pointer:
        pointer_token = existing_pointer[0]
    else:
        pointer_token = generate_token(pointer)  # Generate a token for the pointer word
        cursor.execute('INSERT OR IGNORE INTO articles (token, name) VALUES (?, ?)', (pointer_token, pointer))

    conn.commit()
    conn.close()
    return pointer_token


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
        return render_template('index.html', wiki_title=name, wiki_content=info_text)
    else:
        return "Article not found + ", 404


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
