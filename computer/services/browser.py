import os
import json
from typing import Optional
import asyncio
import aiohttp
import subprocess
from pathlib import Path

class BrowserManager:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._cdp_endpoint: Optional[str] = None
        self._chrome_process = None
        
        # Default Chrome paths for Windows
        self._chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"C:\Program Files (x86)\Chromium\Application\chrome.exe"
        ]

    def _find_chrome(self) -> Optional[str]:
        """Find Chrome/Chromium executable"""
        for path in self._chrome_paths:
            if Path(path).exists():
                return path
        return None

    async def _get_ws_endpoint(self) -> str:
        """Get the WebSocket endpoint from Chrome's debugging API."""
        async with aiohttp.ClientSession() as session:
            for _ in range(5):
                try:
                    async with session.get('http://localhost:9222/json/version') as response:
                        data = await response.json()
                        return data['webSocketDebuggerUrl']
                except:
                    await asyncio.sleep(1)
            raise RuntimeError("Could not connect to Chrome's debugging API")

    async def start_browser(self) -> str:
        """Start Chrome with remote debugging and return CDP endpoint URL."""
        async with self._lock:
            if self._cdp_endpoint is not None:
                return self._cdp_endpoint
            
            chrome_path = self._find_chrome()
            if not chrome_path:
                raise RuntimeError("Could not find Chrome/Chromium installation")

            # Create user data directory if it doesn't exist
            user_data_dir = Path(r"C:\chrome-user-data")
            user_data_dir.mkdir(exist_ok=True)
            
            # Launch Chrome with remote debugging enabled
            self._chrome_process = subprocess.Popen([
                chrome_path,
                f"--user-data-dir={user_data_dir}",
                "--remote-debugging-port=9222",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--window-size=1024,768"
            ])
            
            # Get the actual WebSocket endpoint
            self._cdp_endpoint = await self._get_ws_endpoint()
            
            return self._cdp_endpoint

    async def stop_browser(self):
        """Stop the browser instance."""
        async with self._lock:
            if self._chrome_process:
                self._chrome_process.terminate()
                try:
                    self._chrome_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._chrome_process.kill()
                self._chrome_process = None
            
            self._cdp_endpoint = None

    @property 
    def cdp_endpoint(self) -> Optional[str]:
        """Get current CDP endpoint if browser is running."""
        return self._cdp_endpoint

browser_manager = BrowserManager()
