import subprocess
import time
import re
import logging
import requests
from threading import Thread

logger = logging.getLogger(__name__)


class CloudflareTunnel:
    def __init__(self, port=5001):
        self.port = port
        self.process = None
        self.public_url = None

    def start(self):
        """Start cloudflared tunnel and extract the public URL"""
        logger.info(f"Starting cloudflared tunnel for port {self.port}...")

        # Start cloudflared process
        self.process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://localhost:{self.port}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        # Read output to find the public URL
        for line in self.process.stdout:
            logger.debug(f"cloudflared: {line.strip()}")
            # Look for the URL in output (format: https://something.trycloudflare.com)
            match = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if match:
                self.public_url = match.group(0)
                logger.info(f"Tunnel established: {self.public_url}")
                return self.public_url

        raise Exception("Failed to extract public URL from cloudflared")

    def stop(self):
        """Stop the tunnel"""
        if self.process:
            logger.info("Stopping cloudflared tunnel...")
            self.process.terminate()
            self.process.wait()

    def get_url(self):
        """Get the public URL"""
        return self.public_url


def update_splitwise_callback(public_url):
    """
    Update Splitwise OAuth callback URL
    Note: Splitwise doesn't have an API to update app settings automatically.
    You'll need to do this manually or use their developer portal.
    This function is a placeholder for any other automation you might need.
    """
    logger.warning("Splitwise callback URL must be updated manually at:")
    logger.warning(f"https://secure.splitwise.com/apps → Your App → OAuth redirect_uri")
    logger.warning(f"Set it to: {public_url}/callback")