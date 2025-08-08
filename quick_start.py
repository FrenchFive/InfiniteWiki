#!/usr/bin/env python3
"""
Quick start script for InfiniteWiki with optimized performance.
"""

import os
import sys
import subprocess
import time
import requests
from pathlib import Path
import dotenv

dotenv.load_dotenv()

def check_dependencies():
    """Check if all required dependencies are installed."""
    try:
        import flask
        import openai
        import redis
        import spacy
        print("✅ All dependencies are installed")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please run: pip install -r requirements.txt")
        return False

def check_redis():
    """Check if Redis is running."""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis is running")
        return True
    except Exception as e:
        print("⚠️  Redis is not running (optional but recommended)")
        print("To start Redis: redis-server")
        return False

def check_openai_key():
    """Check if OpenAI API key is set."""
    key = os.getenv("OPENAI_API_KEY")
    if key:
        print("✅ OpenAI API key is configured")
        return True
    else:
        print("❌ OpenAI API key not found")
        print("Please set OPENAI_API_KEY environment variable")
        return False

def start_application():
    """Start the optimized application."""
    print("\n🚀 Starting InfiniteWiki with optimized performance...")
    
    try:
        # Import and run the optimized application
        from app_optimized import app, init_db, startup
        
        # Initialize database
        print("📊 Initializing database...")
        init_db()
        
        # Initialize Redis and pre-compute tokens
        print("⚡ Initializing optimizations...")
        startup()
        
        print("✅ Application ready!")
        print("🌐 Server running at: http://localhost:5000")
        print("📈 Performance optimizations enabled:")
        print("   • Redis caching")
        print("   • Database connection pooling")
        print("   • Pre-computed word tokens")
        print("   • Optimized OpenAI API calls")
        print("   • Batch processing")
        
        # Start the Flask app
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )
        
    except Exception as e:
        print(f"❌ Failed to start application: {e}")
        return False

def test_performance():
    """Run a quick performance test."""
    print("\n🧪 Running quick performance test...")
    
    try:
        # Test home page
        start_time = time.time()
        response = requests.get("http://localhost:5000/", timeout=10)
        home_time = time.time() - start_time
        
        if response.status_code == 200:
            print(f"✅ Home page load: {home_time:.2f}s")
        else:
            print(f"❌ Home page failed: {response.status_code}")
        
        # Test article generation
        start_time = time.time()
        response = requests.get("http://localhost:5000/api/article/test-article", timeout=30)
        gen_time = time.time() - start_time
        
        if response.status_code == 200:
            print(f"✅ Article generation: {gen_time:.2f}s")
            if gen_time <= 5.0:
                print("🎉 Performance target achieved! (< 5 seconds)")
            else:
                print(f"⚠️  Generation time ({gen_time:.2f}s) exceeds target (5s)")
        else:
            print(f"❌ Article generation failed: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Performance test failed: {e}")

def main():
    """Main function."""
    print("🚀 InfiniteWiki Quick Start")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        return
    
    # Check Redis
    check_redis()
    
    # Check OpenAI key
    if not check_openai_key():
        return
    
    # Start application
    if start_application():
        # Give the app a moment to start
        time.sleep(2)
        
        # Run performance test
        test_performance()
        
        print("\n📚 For more information, see OPTIMIZATION_GUIDE.md")
        print("🧪 For comprehensive testing, run: python performance_test.py")

if __name__ == '__main__':
    main()
