import ssl
import urllib.parse
from .config import ALLOWED_DOMAINS

def validate_url(url):
    """Validate if URL is allowed and secure."""
    parsed = urllib.parse.urlparse(url)
    
    if parsed.scheme not in ['https']:
        raise ValueError("Only HTTPS URLs are allowed")
    
    if parsed.netloc not in ALLOWED_DOMAINS:
        raise ValueError(f"Domain {parsed.netloc} is not in allowed domains")
    
    return True

def create_secure_context():
    """Create a secure SSL context for requests."""
    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context