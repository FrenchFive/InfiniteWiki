import asyncio
import uuid
import datetime
import dotenv
import os
import re
import spacy

from flask import Flask, render_template
import asyncpg
import openai

NLP = spacy.load("en_core_web_sm")

dotenv.load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

DB_POOL: asyncpg.Pool | None = None

app = Flask(__name__)


@app.before_serving
async def startup():
    global DB_POOL
    DB_POOL = await asyncpg.create_pool(DATABASE_URL)
    await init_db()


@app.after_serving
async def shutdown():
    if DB_POOL is not None:
        await DB_POOL.close()

async def check_tokens(words):
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch('SELECT name FROM articles WHERE name = ANY($1::text[])', words)
    known = {row['name'] for row in rows}
    return [word for word in words if word not in known]

async def tokenize(words, chunk_size: int = 10):
    """Tokenize the words and add them to the database."""

    async def process_chunk(chunk):
        async with DB_POOL.acquire() as conn:
            for word in chunk:
                pointer_token, pointer = await check_pointer(word)
                if pointer_token == 0:
                    token = generate_token(word)
                    await conn.execute(
                        'INSERT INTO articles (token, name) VALUES ($1, $2) ON CONFLICT (name) DO NOTHING',
                        token,
                        word,
                    )
                else:
                    await conn.execute(
                        'INSERT INTO articles (token, name, pointer) VALUES ($1, $2, 0) ON CONFLICT (name) DO NOTHING',
                        pointer_token,
                        pointer,
                    )
                    await conn.execute(
                        'INSERT INTO articles (token, name, pointer) VALUES ($1, $2, 1) ON CONFLICT (name) DO NOTHING',
                        pointer_token,
                        word,
                    )

    chunks = [words[i : i + chunk_size] for i in range(0, len(words), chunk_size)]
    await asyncio.gather(*(process_chunk(chunk) for chunk in chunks))

async def linkenize(words):
    html = re.compile('<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});')
    async with DB_POOL.acquire() as conn:
        linkenized_words = []
        for word in words:
            word_clean = word.strip().lower()
            word_clean = re.sub(html, '', word_clean)
            word_clean = re.sub(r'[^a-z0-9]', '', word_clean)

            if len(word_clean) == 0:
                linkenized_words.append(word)
            else:
                data = await conn.fetchrow('SELECT token FROM articles WHERE name = $1', word_clean)
                if data:
                    token = data['token']
                    linkenized_words.append(f"<a href='/article/{token}'>{word}</a> ")
                else:
                    linkenized_words.append(word)

    return linkenized_words

def generate_token(word):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, word))

async def generate_links(text):
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
    li_unknown = await check_tokens(cleaned_list)
    print(f"Tokenized words : {len(cleaned_list) - len(li_unknown)}")
    print(f"Unknown words : {len(li_unknown)}")

    await tokenize(li_unknown)

    link_list = await linkenize(word_list)

    paragraph = " ".join(link_list)
    return paragraph

async def init_db():
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                token TEXT,
                name TEXT UNIQUE,
                pointer INTEGER DEFAULT 0,
                info_text TEXT DEFAULT '',
                num_visits INTEGER DEFAULT 0,
                discovered_by TEXT DEFAULT '',
                discovery_time TEXT DEFAULT ''
            )
            '''
        )

        name = "Infinite Wiki"
        token = generate_token(name)

        def read_default():
            with open('default_article.txt', 'r', encoding='utf-8') as file:
                return file.read()

        text = await asyncio.to_thread(read_default)

        await conn.execute(
            '''
            INSERT INTO articles (token, name, info_text, discovered_by, discovery_time)
            VALUES ($1, $2, $3, $4, $5) ON CONFLICT (name) DO NOTHING
            ''',
            token,
            name,
            text,
            "Lau&Five",
            "TODAY",
        )

async def generate_article(token, name, user):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = await asyncio.to_thread(
        client.responses.create,
        model="gpt-4.1",
        input=[
            {
                "role": "system",
                "content": "You are an expert in creating detailed articles for a wiki (at least 500 words). Only output the article text without any additional commentary. Be creative and dont hesitate to invent new information if necessary.",
            },
            {
                "role": "system",
                "content": "Use HTML formatting to structure the article. Do not include any links or references to external sources. Do not define the html no <head> or <body> tags nor <html> or <!DOCTYPE html>, maximum size should be h2. Do not include the title of the article, start with the introduction.",
            },
            {
                "role": "user",
                "content": f"Create a detailed article about {name}.",
            }
        ],
    )
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            '''
            UPDATE articles
            SET info_text = $1, num_visits = num_visits + 1, discovered_by = $2, discovery_time = $3
            WHERE token = $4 and pointer = 0
            ''',
            response.output_text,
            user,
            datetime.datetime.now(),
            token,
        )
    return response.output_text

async def check_pointer(word):
    doc = await asyncio.to_thread(NLP, word)
    for token in doc:
        if token.is_oov and token.lemma_ == word:
            pointer = "<UNK>"
        else:
            pointer = token.lemma_.lower()
    if pointer == "<UNK>":
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = await asyncio.to_thread(
            client.responses.create,
            model="gpt-4.1-nano-2025-04-14",
            input=[
                {
                    "role": "system",
                    "content": "If the word is plural, output the singular word. If the word is a verb, output the unconjugated form. ONLY OUTPUT 1 WORD.",
                },
                {"role": "user", "content": f"{word}"},
            ],
        )
        pointer = response.output_text.strip().lower()
    pointer = re.sub(r'[^a-z0-9]', '', pointer)
    if word == pointer:
        return 0, ""
    async with DB_POOL.acquire() as conn:
        existing_pointer = await conn.fetchrow('SELECT token FROM articles WHERE name = $1', pointer)
        if existing_pointer:
            pointer_token = existing_pointer['token']
        else:
            pointer_token = generate_token(pointer)
    return pointer_token, pointer

async def get_stats():
    async with DB_POOL.acquire() as conn:
        total_articles = await conn.fetchval(
            "SELECT COUNT(*) FROM articles WHERE pointer = 0 and info_text != ''"
        )
        total_undiscovered = await conn.fetchval(
            "SELECT COUNT(*) FROM articles WHERE info_text = '' and pointer = 0"
        )
        most_active_user = await conn.fetchrow(
            "SELECT discovered_by, COUNT(*) AS discoveries FROM articles WHERE discovered_by != '' GROUP BY discovered_by ORDER BY discoveries DESC LIMIT 1"
        )
    stat = {
        "total_articles": total_articles,
        "total_undiscovered": total_undiscovered,
        "most_active_user": most_active_user["discovered_by"] if most_active_user else "None",
    }
    return stat

@app.route('/')
async def index():
    async with DB_POOL.acquire() as conn:
        article = await conn.fetchrow('SELECT * FROM articles WHERE id = $1', 1)
    info_text = await generate_links(article["info_text"])
    return render_template(
        'index.html',
        wiki_title=article["name"],
        wiki_content=info_text,
        stats=await get_stats(),
    )


@app.route('/article/<token>')
async def article(token):
    async with DB_POOL.acquire() as conn:
        article = await conn.fetchrow(
            'SELECT * FROM articles WHERE token = $1 AND pointer = $2',
            token,
            0,
        )
    if article:
        token = article["token"]
        name = article["name"]
        info_text = article["info_text"]
        if len(info_text) == 0:
            info_text = await generate_article(token, name, "user")
        links = await generate_links(info_text)
        return render_template(
            'index.html',
            wiki_title=name,
            wiki_content=links,
            stats=await get_stats(),
        )
    else:
        return "Article not found + ", 404


if __name__ == '__main__':
    app.run(debug=True)
