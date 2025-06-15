"""
Custom middleware for database connection management
"""
import logging
from django.db import connection
from django.db.utils import OperationalError, InterfaceError
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class DatabaseHealthCheckMiddleware:
    """
    Middleware to ensure database connections are healthy before processing requests
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check database connection health before processing request
        if not self.check_database_connection():
            logger.warning("Database connection unhealthy, attempting to reconnect")
            self.ensure_database_connection()
        
        response = self.get_response(request)
        return response

    def check_database_connection(self):
        """
        Check if database connection is healthy
        """
        try:
            # Simple query to test connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except (OperationalError, InterfaceError) as e:
            logger.warning(f"Database connection check failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during database connection check: {e}")
            return False

    def ensure_database_connection(self):
        """
        Ensure database connection is available
        """
        try:
            # Close existing connection if it exists
            if connection.connection:
                try:
                    connection.close()
                except:
                    pass
            
            # Force a new connection
            connection.ensure_connection()
            
            # Test the new connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            
            logger.info("Database connection restored successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore database connection: {e}")
            return False

    def process_exception(self, request, exception):
        """
        Handle database-related exceptions
        """
        if isinstance(exception, (OperationalError, InterfaceError)):
            logger.error(f"Database error in request: {exception}")
            
            # Try to restore connection
            if self.ensure_database_connection():
                logger.info("Database connection restored after error")
            else:
                logger.error("Failed to restore database connection after error")
                return JsonResponse({
                    'status': 'error',
                    'message': 'Database connection error, please try again later'
                }, status=503)
        
        return None


class ConnectionCleanupMiddleware:
    """
    Middleware to clean up database connections after each request
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        finally:
            # Clean up connections after each request to prevent leaks
            try:
                # Log query count for debugging
                if hasattr(connection, 'queries') and connection.queries:
                    query_count = len(connection.queries)
                    if query_count > 50:  # Log if too many queries (increased threshold)
                        logger.warning(f"High query count in request: {query_count}")

                # Close connection if it's been open too long or has issues
                if connection.connection and hasattr(connection.connection, 'ping'):
                    try:
                        connection.connection.ping(reconnect=False)
                    except:
                        # Connection is stale, close it
                        connection.close()

            except Exception as e:
                logger.warning(f"Error during connection cleanup: {e}")
                try:
                    connection.close()
                except:
                    pass
        
        return response
