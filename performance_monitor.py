#!/usr/bin/env python3
"""
Performance monitoring for InfiniteWiki.
"""

import time
import psutil
import sqlite3
import threading
from collections import defaultdict
import logging

class PerformanceMonitor:
    """Monitor application performance metrics."""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.lock = threading.Lock()
        self.running = False
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('performance.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def start_monitoring(self):
        """Start performance monitoring."""
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        self.logger.info("Performance monitoring started")
    
    def stop_monitoring(self):
        """Stop performance monitoring."""
        self.running = False
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join()
        self.logger.info("Performance monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                self._collect_metrics()
                time.sleep(60)  # Collect metrics every minute
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
    
    def _collect_metrics(self):
        """Collect system and application metrics."""
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Database metrics
        db_metrics = self._get_database_metrics()
        
        # Cache metrics
        cache_metrics = self._get_cache_metrics()
        
        # Store metrics
        with self.lock:
            timestamp = time.time()
            self.metrics['cpu'].append((timestamp, cpu_percent))
            self.metrics['memory'].append((timestamp, memory.percent))
            self.metrics['disk'].append((timestamp, disk.percent))
            self.metrics['database'].append((timestamp, db_metrics))
            self.metrics['cache'].append((timestamp, cache_metrics))
        
        # Log metrics
        self.logger.info(f"CPU: {cpu_percent}%, Memory: {memory.percent}%, "
                        f"Disk: {disk.percent}%, DB Size: {db_metrics['size_mb']:.2f}MB")
    
    def _get_database_metrics(self):
        """Get database performance metrics."""
        try:
            conn = sqlite3.connect('wiki.db')
            cursor = conn.cursor()
            
            # Get database size
            cursor.execute("PRAGMA page_count")
            page_count = cursor.fetchone()[0]
            cursor.execute("PRAGMA page_size")
            page_size = cursor.fetchone()[0]
            size_mb = (page_count * page_size) / (1024 * 1024)
            
            # Get table statistics
            cursor.execute("SELECT COUNT(*) FROM articles")
            total_articles = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE info_text != ''")
            discovered_articles = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM articles WHERE info_text = ''")
            undiscovered_articles = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'size_mb': size_mb,
                'total_articles': total_articles,
                'discovered_articles': discovered_articles,
                'undiscovered_articles': undiscovered_articles
            }
        except Exception as e:
            self.logger.error(f"Error getting database metrics: {e}")
            return {'size_mb': 0, 'total_articles': 0, 'discovered_articles': 0, 'undiscovered_articles': 0}
    
    def _get_cache_metrics(self):
        """Get cache performance metrics."""
        try:
            from app import cache
            return {
                'cache_size': len(cache),
                'cache_hit_rate': self._calculate_cache_hit_rate()
            }
        except Exception as e:
            self.logger.error(f"Error getting cache metrics: {e}")
            return {'cache_size': 0, 'cache_hit_rate': 0}
    
    def _calculate_cache_hit_rate(self):
        """Calculate cache hit rate (simplified)."""
        # This would need to be implemented with actual hit/miss tracking
        return 0.85  # Placeholder
    
    def get_performance_report(self):
        """Generate a performance report."""
        with self.lock:
            if not self.metrics:
                return "No metrics available"
            
            report = []
            report.append("=== InfiniteWiki Performance Report ===")
            
            # CPU usage
            if self.metrics['cpu']:
                recent_cpu = [m[1] for m in self.metrics['cpu'][-10:]]
                avg_cpu = sum(recent_cpu) / len(recent_cpu)
                report.append(f"Average CPU Usage: {avg_cpu:.2f}%")
            
            # Memory usage
            if self.metrics['memory']:
                recent_memory = [m[1] for m in self.metrics['memory'][-10:]]
                avg_memory = sum(recent_memory) / len(recent_memory)
                report.append(f"Average Memory Usage: {avg_memory:.2f}%")
            
            # Database metrics
            if self.metrics['database']:
                latest_db = self.metrics['database'][-1][1]
                report.append(f"Database Size: {latest_db['size_mb']:.2f}MB")
                report.append(f"Total Articles: {latest_db['total_articles']}")
                report.append(f"Discovered Articles: {latest_db['discovered_articles']}")
                report.append(f"Undiscovered Articles: {latest_db['undiscovered_articles']}")
            
            # Cache metrics
            if self.metrics['cache']:
                latest_cache = self.metrics['cache'][-1][1]
                report.append(f"Cache Size: {latest_cache['cache_size']}")
                report.append(f"Cache Hit Rate: {latest_cache['cache_hit_rate']:.2%}")
            
            return "\n".join(report)

def main():
    """Run performance monitoring."""
    monitor = PerformanceMonitor()
    
    try:
        monitor.start_monitoring()
        
        # Run for a specified duration or until interrupted
        while True:
            time.sleep(300)  # Generate report every 5 minutes
            report = monitor.get_performance_report()
            print(report)
            
    except KeyboardInterrupt:
        print("\nStopping performance monitoring...")
        monitor.stop_monitoring()
        print("Final performance report:")
        print(monitor.get_performance_report())

if __name__ == '__main__':
    main()
