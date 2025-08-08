#!/usr/bin/env python3
"""
Production server for InfiniteWiki with optimized performance.
"""

import os
import sys
from gunicorn.app.wsgiapp import WSGIApplication
from gevent import monkey

# Patch for gevent compatibility
monkey.patch_all()

class InfiniteWikiApplication(WSGIApplication):
    """Custom WSGI application for InfiniteWiki."""
    
    def __init__(self):
        self.app_uri = 'app:app'
        self.options = {
            'bind': '0.0.0.0:5000',
            'workers': 4,
            'worker_class': 'gevent',
            'worker_connections': 1000,
            'max_requests': 1000,
            'max_requests_jitter': 50,
            'timeout': 30,
            'keepalive': 2,
            'preload_app': True,
            'access_logfile': '-',
            'error_logfile': '-',
            'loglevel': 'info',
            'access_log_format': '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s',
        }
        super().__init__()

def main():
    """Run the production server."""
    # Set environment variables for performance
    os.environ.setdefault('FLASK_ENV', 'production')
    os.environ.setdefault('FLASK_DEBUG', '0')
    
    # Initialize database
    from app import init_db
    init_db()
    
    # Run the application
    InfiniteWikiApplication().run()

if __name__ == '__main__':
    main()
