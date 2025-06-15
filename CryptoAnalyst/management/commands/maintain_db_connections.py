"""
Management command to maintain database connections
Run this as a cron job to prevent connection timeouts
"""
import time
import logging
from django.core.management.base import BaseCommand
from django.db import connection, connections
from django.db.utils import OperationalError, InterfaceError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Maintain database connections to prevent timeouts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=300,  # 5 minutes
            help='Interval between connection checks in seconds'
        )
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run as daemon (continuous loop)'
        )

    def handle(self, *args, **options):
        interval = options['interval']
        daemon_mode = options['daemon']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting database connection maintenance (interval: {interval}s)')
        )
        
        if daemon_mode:
            self.run_daemon(interval)
        else:
            self.check_and_maintain_connections()

    def run_daemon(self, interval):
        """Run as daemon with continuous monitoring"""
        try:
            while True:
                self.check_and_maintain_connections()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('Database maintenance daemon stopped'))

    def check_and_maintain_connections(self):
        """Check and maintain all database connections"""
        for alias in connections:
            try:
                self.maintain_connection(alias)
            except Exception as e:
                logger.error(f"Error maintaining connection {alias}: {e}")

    def maintain_connection(self, alias='default'):
        """Maintain a specific database connection"""
        conn = connections[alias]
        
        try:
            # Check if connection exists and is healthy
            if conn.connection is None:
                self.stdout.write(f"Connection {alias}: No active connection")
                return
            
            # Test connection with a simple query
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
            if result and result[0] == 1:
                self.stdout.write(
                    self.style.SUCCESS(f"Connection {alias}: Healthy")
                )
            else:
                raise OperationalError("Invalid query result")
                
        except (OperationalError, InterfaceError) as e:
            self.stdout.write(
                self.style.WARNING(f"Connection {alias}: Unhealthy ({e}), reconnecting...")
            )
            
            try:
                # Close stale connection
                conn.close()
                
                # Force new connection
                conn.ensure_connection()
                
                # Test new connection
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                
                self.stdout.write(
                    self.style.SUCCESS(f"Connection {alias}: Reconnected successfully")
                )
                
            except Exception as reconnect_error:
                self.stdout.write(
                    self.style.ERROR(f"Connection {alias}: Failed to reconnect ({reconnect_error})")
                )
                logger.error(f"Failed to reconnect database {alias}: {reconnect_error}")
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Connection {alias}: Unexpected error ({e})")
            )
            logger.error(f"Unexpected error checking connection {alias}: {e}")

    def get_connection_info(self, alias='default'):
        """Get connection information for debugging"""
        conn = connections[alias]
        info = {
            'alias': alias,
            'vendor': conn.vendor,
            'connection_exists': conn.connection is not None,
        }
        
        if conn.connection:
            try:
                info['server_version'] = conn.connection.get_server_info()
                info['thread_id'] = conn.connection.thread_id()
            except:
                pass
        
        return info
