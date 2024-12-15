import os
import json
from typing import Optional
import asyncio
import aiohttp
import subprocess
from playwright.async_api import async_playwright, Browser

class BrowserManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._cdp_endpoint: Optional[str] = None
        self._display = os.environ.get('DISPLAY', ':1')
        self._socat_process = None

    async def _get_ws_endpoint(self) -> str:
        """Get the WebSocket endpoint from Chrome's debugging API."""
        async with aiohttp.ClientSession() as session:
            for _ in range(5):
                try:
                    async with session.get('http://localhost:9222/json/version') as response:
                        data = await response.json()
                        # Replace with forwarded port
                        return data['webSocketDebuggerUrl'].replace('9222', '9223')
                except:
                    await asyncio.sleep(1)
            raise RuntimeError("Could not connect to Chrome's debugging API")

    async def start_browser(self) -> str:
        """Start Chrome with remote debugging and return CDP endpoint URL."""
        async with self._lock:
            if self._cdp_endpoint is not None:
                return self._cdp_endpoint
            
            # Launch Chrome with remote debugging enabled
            subprocess.Popen([
                'chromium',
                '--remote-debugging-port=9222',
                '--no-first-run',
                '--no-default-browser-check',
                f'--display={self._display}'
            ])
            
            # Start socat to forward the port
            self._socat_process = subprocess.Popen([
                'socat',
                'TCP-LISTEN:9223,fork,reuseaddr',
                'TCP:127.0.0.1:9222'
            ])
            
            # Get the actual WebSocket endpoint
            self._cdp_endpoint = await self._get_ws_endpoint()
            # Replace localhost with 0.0.0.0
            self._cdp_endpoint = self._cdp_endpoint.replace('localhost', '0.0.0.0')
            
            return self._cdp_endpoint

    async def stop_browser(self):
        """Stop the browser instance."""
        async with self._lock:
            # Only stop the port forwarding, leave Chrome running
            if self._socat_process:
                self._socat_process.terminate()
                self._socat_process = None
            
            self._cdp_endpoint = None

    @property 
    def cdp_endpoint(self) -> Optional[str]:
        """Get current CDP endpoint if browser is running."""
        return self._cdp_endpoint

browser_manager = BrowserManager()
