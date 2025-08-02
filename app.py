import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import datetime

openai.api_key = "YOUR_OPENAI_KEY"

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('wiki.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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

if __name__ == '__main__':
    app.run(debug=True)
