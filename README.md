# InfiniteWiki

## SETUP 

Create a virtual environment and install the requirements:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows use `.\.venv\Scripts\activate`
pip install -r .\requirements.txt
```

Set the `DATABASE_URL` environment variable to point to your Postgres instance. For example:

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/wiki
```
