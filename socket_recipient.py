import socket
import logging
from typing import Tuple
import signal
import sys

# Constants
HOST = 'localhost'
PORT = 65432
BUFFER_SIZE = 1024

class SocketServer:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self.socket = None
        self.running = True
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle graceful shutdown on signals"""
        self.logger.info("Shutting down server...")
        self.running = False
        if self.socket:
            self.socket.close()
        sys.exit(0)

    def handle_client(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        """Handle individual client connection"""
        self.logger.info(f"Connected by {addr}")
        try:
            while self.running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                
                message = data.decode()
                self.logger.info(f"Received: {message}")
                
                # Process received data here
                # Add your processing logic
                
        except Exception as e:
            self.logger.error(f"Error handling client {addr}: {e}")
        finally:
            conn.close()
            self.logger.info(f"Connection closed for {addr}")

    def start(self):
        """Start the socket server"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as self.socket:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.bind((self.host, self.port))
                self.socket.listen()
                
                self.logger.info(f"Server listening on {self.host}:{self.port}")
                
                while self.running:
                    try:
                        conn, addr = self.socket.accept()
                        with conn:
                            self.handle_client(conn, addr)
                    except socket.error as e:
                        if self.running:  # Only log if not shutting down
                            self.logger.error(f"Socket error: {e}")
                            
        except Exception as e:
            self.logger.error(f"Server error: {e}")
        finally:
            if self.socket:
                self.socket.close()
            self.logger.info("Server stopped")

if __name__ == "__main__":
    server = SocketServer()
    server.start() 
