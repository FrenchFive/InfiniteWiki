import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for
import openai
import datetime

openai.api_key = "YOUR_OPENAI_KEY"

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
