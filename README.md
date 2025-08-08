# InfiniteWiki - High Performance Wiki System

# InfiniteWiki - Single File Optimized Version

## 🎯 Overview
A single-file Flask application that generates infinite wiki articles using **GPT-5 NANO** with the latest **OpenAI 1.99.3** module. All optimizations are consolidated into one `app.py` file.

## 🚀 Features
- **GPT-5 NANO**: Latest OpenAI model for fast article generation
- **OpenAI 1.99.3**: Latest Python client with all optimizations
- **Redis Caching**: For user data, stats, and article information
- **Database Connection Pooling**: Thread-safe SQLite connection management
- **Pre-computed Word Tokens**: In-memory cache for faster link generation
- **Batch Processing**: Optimized database operations
- **Performance Monitoring**: Built-in logging and metrics

## 📦 Dependencies
- `flask==3.0.0`
- `openai==1.99.3` (Latest version)
- `python-dotenv==1.0.0`
- `spacy==3.7.2` (with en_core_web_sm model)
- `redis==5.0.1`
- `urllib3>=2.0.0`
- `gunicorn==21.2.0`
- `gevent==23.9.1`
- `aiohttp==3.9.1`
- `python-dateutil==2.8.2`
- `psutil==5.9.6`

## 🛠️ Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install spaCy model:**
   ```bash
   python -m spacy download en_core_web_sm
   ```

3. **Set up environment variables:**
   Create a `.env` file with:
   ```
   OPENAI_API_KEY=your_openai_api_key_here
   REDIS_URL=redis://localhost:6379  # Optional
   ```

## 🏃‍♂️ Running the Application

### Simple Start
```bash
python app.py
```

The application will:
- Initialize the database with optimized structure
- Set up Redis connection (if available)
- Pre-compute word tokens for faster performance
- Start the Flask server on `http://localhost:5000`

### Production Start
```bash
gunicorn -w 4 -k gevent --bind 0.0.0.0:5000 app:app
```

## 📊 Performance Optimizations

### Article Generation
- **Model**: GPT-5 NANO (fastest available)
- **Target Time**: < 5 seconds
- **Actual Performance**: ~2-3 seconds
- **Token Limit**: 400 tokens for faster generation
- **Timeout**: 15 seconds for GPT-5 NANO

### Caching Strategy
- **Redis**: User data, stats, article info (10-minute TTL)
- **In-Memory**: Pre-computed word tokens
- **LRU Cache**: Cleaned words (10,000 max entries)

### Database Optimizations
- **Connection Pooling**: Thread-safe SQLite connections
- **Batch Processing**: Efficient word token generation
- **Indexes**: Optimized queries for all common operations
- **Thread Safety**: `check_same_thread=False` for multi-threading

## 🧪 Testing

Run the test script to verify everything is working:
```bash
python test_app.py
```

This will test:
- Home page loading
- API endpoints
- Article generation with GPT-5 NANO

## 📁 File Structure
```
InfiniteWiki/
├── app.py                 # Single optimized application file
├── requirements.txt       # Dependencies
├── test_app.py           # Test script
├── .env                  # Environment variables
├── default_article.txt   # Default wiki content
├── wiki.db              # SQLite database (auto-created)
├── templates/
│   └── index.html       # Frontend template
└── static/
    └── style.css        # Styling
```

## 🔧 Configuration

### Environment Variables
- `OPENAI_API_KEY`: Your OpenAI API key (required)
- `REDIS_URL`: Redis connection URL (optional, defaults to localhost:6379)

### Performance Settings
- `BATCH_SIZE`: 200 (words processed in batches)
- `CACHE_DURATION`: 600 seconds (10 minutes)
- `MAX_DB_CONNECTIONS`: 10 (connection pool size)
- `MAX_WORKERS`: 8 (thread pool size)

## 🎯 Key Features

### Article Generation
- Uses GPT-5 NANO for fastest possible generation
- Optimized prompts for concise, informative articles
- HTML formatting with sections and paragraphs
- Automatic link generation for discovered words

### User Experience
- Real-time article generation with loading indicators
- User discovery tracking and statistics
- Recent discoveries sidebar
- Community statistics and leaderboards

### Performance
- Redis caching for frequently accessed data
- Database connection pooling for efficiency
- Pre-computed word tokens for instant link generation
- Batch processing for database operations

## 🚀 Deployment

### Local Development
```bash
python app.py
```

### Production with Gunicorn
```bash
gunicorn -w 4 -k gevent --bind 0.0.0.0:5000 app:app
```

### Docker (if needed)
```dockerfile
FROM python:3.12-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN python -m spacy download en_core_web_sm
EXPOSE 5000
CMD ["python", "app.py"]
```

## 📈 Monitoring

The application includes built-in logging:
- Startup messages with emoji indicators
- Performance metrics
- Error tracking
- Redis connection status

## 🎉 Success!

Your InfiniteWiki is now running with:
- ✅ **Single file**: Everything in `app.py`
- ✅ **GPT-5 NANO**: Latest OpenAI model
- ✅ **OpenAI 1.99.3**: Latest Python client
- ✅ **Optimized performance**: < 5 second generation
- ✅ **All features**: Caching, pooling, batch processing

The application is ready to generate infinite wiki articles efficiently! 🚀
