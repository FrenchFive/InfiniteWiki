import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import datetime

openai.api_key = "YOUR_OPENAI_KEY"

app = Flask(__name__)

# --- DB Setup ---
def get_db():
    conn = sqlite3.connect('wiki.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS pages (
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

init_db()

# --- Helper: ChatGPT ---
def generate_page_info(name):
    prompt = f"Write a detailed encyclopedia entry about '{name}'."
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # Or gpt-4 if you have access
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# --- Flask Routes ---
@app.route('/')
def home():
    return "Welcome to Wiki AI! Go to /page/<your-page-name>"

@app.route('/page/<name>', methods=['GET'])
def view_page(name):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM pages WHERE name = ?', (name,))
    row = c.fetchone()
    user = request.remote_addr  # Use IP for now as 'who discovered'

    if row:
        # Increment visit count
        c.execute('UPDATE pages SET num_visits = num_visits + 1 WHERE name = ?', (name,))
        conn.commit()
        conn.close()
        return render_template("page.html", name=row['name'], info_text=row['info_text'],
                               num_visits=row['num_visits'] + 1, discovered_by=row['discovered_by'],
                               discovery_time=row['discovery_time'])
    else:
        # Generate page with ChatGPT
        info_text = generate_page_info(name)
        now = datetime.datetime.utcnow().isoformat()
        c.execute('''
            INSERT INTO pages (name, info_text, num_visits, discovered_by, discovery_time)
            VALUES (?, ?, 1, ?, ?)
        ''', (name, info_text, user, now))
        conn.commit()
        conn.close()
        return render_template("page.html", name=name, info_text=info_text,
                               num_visits=1, discovered_by=user, discovery_time=now)

# --- Run ---
if __name__ == '__main__':
    app.run(debug=True)
