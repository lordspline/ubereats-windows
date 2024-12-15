import asyncio
import os
from typing import ClassVar, Literal

from anthropic.types.beta import BetaToolBash20241022Param

from .base import BaseAnthropicTool, CLIResult, ToolError, ToolResult


class _BashSession:
    """A session of a command shell."""

    _started: bool
    _process: asyncio.subprocess.Process

    command: str = "cmd.exe"
    _output_delay: float = 0.2  # seconds
    _timeout: float = 120.0  # seconds
    _sentinel: str = "<<exit>>"

    def __init__(self):
        self._started = False
        self._timed_out = False

    async def start(self):
        if self._started:
            return

        self._process = await asyncio.create_subprocess_shell(
            self.command,
            shell=True,
            bufsize=0,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._started = True

    def stop(self):
        """Terminate the shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return
        self._process.terminate()

    async def run(self, command: str):
        """Execute a command in the shell."""
        if not self._started:
            raise ToolError("Session has not started.")
        if self._process.returncode is not None:
            return ToolResult(
                system="tool must be restarted",
                error=f"shell has exited with returncode {self._process.returncode}",
            )
        if self._timed_out:
            raise ToolError(
                f"timed out: shell has not returned in {self._timeout} seconds and must be restarted",
            )

        # we know these are not None because we created the process with PIPEs
        assert self._process.stdin
        assert self._process.stdout
        assert self._process.stderr

        # Add echo %errorlevel% to get command execution status
        cmd_with_sentinel = f"{command} & echo %errorlevel% & echo {self._sentinel}\n"
        
        try:
            # Send command
            self._process.stdin.write(cmd_with_sentinel.encode())
            await self._process.stdin.drain()

            output = ""
            error = ""

            # Read output until sentinel is found
            async with asyncio.timeout(self._timeout):
                while True:
                    # Read one line at a time
                    line = await self._process.stdout.readline()
                    if not line:
                        break
                        
                    line_str = line.decode()
                    
                    # Check for sentinel
                    if self._sentinel in line_str:
                        break
                        
                    output += line_str

            # Get any stderr output
            error = await self._process.stderr.read()
            error = error.decode() if error else ""

            # Clean up output
            output = output.strip()
            error = error.strip()

            return CLIResult(output=output, error=error)

        except asyncio.TimeoutError:
            self._timed_out = True
            raise ToolError(
                f"timed out: shell has not returned in {self._timeout} seconds and must be restarted",
            ) from None


class BashTool(BaseAnthropicTool):
    """
    A tool that allows the agent to run bash commands.
    The tool parameters are defined by Anthropic and are not editable.
    """

    _session: _BashSession | None
    name: ClassVar[Literal["bash"]] = "bash"
    api_type: ClassVar[Literal["bash_20241022"]] = "bash_20241022"

    def __init__(self):
        self._session = None
        super().__init__()

    async def __call__(
        self, command: str | None = None, restart: bool = False, **kwargs
    ):
        if restart:
            if self._session:
                self._session.stop()
            self._session = _BashSession()
            await self._session.start()

            return ToolResult(system="tool has been restarted.")

        if self._session is None:
            self._session = _BashSession()
            await self._session.start()

        if command is not None:
            return await self._session.run(command)

        raise ToolError("no command provided.")

    def to_params(self) -> BetaToolBash20241022Param:
        return {
            "type": self.api_type,
            "name": self.name,
        }
