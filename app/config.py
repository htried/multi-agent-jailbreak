import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Configuration
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
MAX_REQUESTS = int(os.getenv('MAX_REQUESTS_PER_MINUTE', 30))

# Security Configuration
ALLOWED_DOMAINS = os.getenv('ALLOWED_DOMAINS', '').split(',')
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# Logging Configuration
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'agent.log')