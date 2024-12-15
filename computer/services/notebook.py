from fastapi import HTTPException
import asyncio
import json
import os
import uuid
import secrets
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager, get_kernel_spec, NoSuchKernel
from queue import Empty

# Copy all the class definitions and service code from the sample
# Including: CellType, CellStatus, KernelInfo, NotebookCell, Notebook,
# KernelSession, NotebookService

class CellType(str, Enum):
    CODE = "code"
    MARKDOWN = "markdown"
    RAW = "raw"

class CellStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"

class KernelInfo(BaseModel):
    name: str
    display_name: str
    language: str
    file_extension: str
    mimetype: str
    version: Optional[str] = None

class NotebookCell(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: CellType
    content: str
    execution_count: Optional[int] = None
    outputs: List[Dict[str, Any]] = Field(default_factory=list)
    status: CellStatus = CellStatus.IDLE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    error: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Notebook(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    kernel_name: str
    cells: List[NotebookCell] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class KernelSession:
    def __init__(self, kernel_name: str):
        try:
            self.kernel_manager = KernelManager(kernel_name=kernel_name)
            self.kernel_manager.start_kernel()
            self.client = self.kernel_manager.client()
            self.execution_count = 0
            
            # Get kernel info by requesting it from the running kernel
            self.kernel_info = self._get_kernel_info(kernel_name)
        except NoSuchKernel as e:
            raise HTTPException(
                status_code=400,
                detail=f"Kernel {kernel_name} not found. Please ensure it is installed."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start kernel: {str(e)}"
            )

    def _get_kernel_info(self, kernel_name: str) -> KernelInfo:
        """Get detailed information about a kernel"""
        try:
            # Get basic info from kernel spec
            spec = get_kernel_spec(kernel_name)
            
            # Request kernel info from running kernel
            msg_id = self.client.kernel_info()
            reply = self.client.get_shell_msg(timeout=30)
            kernel_info = reply['content']
            
            return KernelInfo(
                name=kernel_name,
                display_name=spec.display_name,
                language=kernel_info.get('language_info', {}).get('name', spec.language),
                file_extension=kernel_info.get('language_info', {}).get('file_extension', ''),
                mimetype=kernel_info.get('language_info', {}).get('mimetype', 'text/plain'),
                version=kernel_info.get('language_info', {}).get('version')
            )
        except Exception as e:
            # Fallback to basic info if kernel info request fails
            return KernelInfo(
                name=kernel_name,
                display_name=spec.display_name,
                language=spec.language,
                file_extension='.txt',
                mimetype='text/plain',
                version=None
            )

    async def execute(self, code: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute code and return outputs"""
        msg_id = self.client.execute(code)
        self.execution_count += 1
        
        outputs = []
        error = None
        
        try:
            while True:
                try:
                    msg = self.client.get_iopub_msg(timeout=timeout)
                    msg_type = msg['header']['msg_type']
                    content = msg['content']

                    if msg_type == 'stream':
                        outputs.append({
                            'type': 'stream',
                            'name': content['name'],
                            'text': content['text']
                        })
                    elif msg_type == 'execute_result':
                        outputs.append({
                            'type': 'execute_result',
                            'data': content['data'],
                            'execution_count': content['execution_count']
                        })
                    elif msg_type == 'display_data':
                        outputs.append({
                            'type': 'display_data',
                            'data': content['data'],
                            'metadata': content.get('metadata', {})
                        })
                    elif msg_type == 'error':
                        error = {
                            'ename': content['ename'],
                            'evalue': content['evalue'],
                            'traceback': content['traceback']
                        }
                        break
                    elif msg_type == 'status' and content['execution_state'] == 'idle':
                        if outputs or error:
                            break
                        
                except Empty:
                    continue
                
        except Exception as e:
            error = {
                'ename': type(e).__name__,
                'evalue': str(e),
                'traceback': []
            }

        return {
            'execution_count': self.execution_count,
            'outputs': outputs,
            'error': error
        }

    def shutdown(self):
        """Shutdown the kernel"""
        try:
            self.client.shutdown()
            self.kernel_manager.shutdown_kernel()
        except Exception:
            pass

class NotebookService:
    def __init__(self):
        self.notebooks: Dict[str, Notebook] = {}
        self.kernel_sessions: Dict[str, KernelSession] = {}
        self.server_port = 8888
        self.notebook_dir = Path("/home/scrapybara/notebooks")
        self.server_process = None
        self.kernel_spec_manager = KernelSpecManager()
        self.setup_directories()

    def setup_directories(self):
        """Create necessary directories"""
        self.notebook_dir.mkdir(parents=True, exist_ok=True)
        
    def list_kernels(self) -> List[KernelInfo]:
        """List available kernel specs"""
        specs = []
        for name in self.kernel_spec_manager.find_kernel_specs():
            try:
                spec = get_kernel_spec(name)
                # Use simpler kernel info for listing
                specs.append(KernelInfo(
                    name=name,
                    display_name=spec.display_name,
                    language=spec.language,
                    file_extension='.txt',  # Default extension
                    mimetype='text/plain',  # Default mimetype
                    version=None
                ))
            except Exception:
                continue
        return specs

    async def create_notebook(self, name: str, kernel_name: str) -> Notebook:
        """Create a new notebook with specified kernel"""
        try:
            notebook = Notebook(name=name, kernel_name=kernel_name)
            self.notebooks[notebook.id] = notebook
            self.kernel_sessions[notebook.id] = KernelSession(kernel_name)
            
            # Save notebook file
            await self._save_notebook(notebook)
            return notebook
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create notebook: {str(e)}"
            )

    async def delete_notebook(self, notebook_id: str):
        """Delete a notebook and its kernel session"""
        if notebook_id in self.kernel_sessions:
            self.kernel_sessions[notebook_id].shutdown()
            del self.kernel_sessions[notebook_id]
        if notebook_id in self.notebooks:
            del self.notebooks[notebook_id]
            
        # Delete notebook file
        notebook_path = self.notebook_dir / f"{notebook_id}.ipynb"
        if notebook_path.exists():
            notebook_path.unlink()

    def get_notebook(self, notebook_id: str) -> Notebook:
        """Get a notebook by ID"""
        if notebook_id not in self.notebooks:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return self.notebooks[notebook_id]

    async def add_cell(
        self,
        notebook_id: str,
        cell_type: CellType,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> NotebookCell:
        """Add a new cell to a notebook"""
        notebook = self.get_notebook(notebook_id)
        cell = NotebookCell(
            type=cell_type,
            content=content,
            metadata=metadata or {}
        )
        notebook.cells.append(cell)
        notebook.updated_at = datetime.utcnow()
        
        # Save notebook file
        await self._save_notebook(notebook)
        return cell

    async def execute_cell(
        self,
        notebook_id: str,
        cell_id: str,
        timeout: int = 30
    ) -> NotebookCell:
        """Execute a specific cell in a notebook"""
        notebook = self.get_notebook(notebook_id)
        session = self.kernel_sessions.get(notebook_id)
        if not session:
            raise HTTPException(status_code=500, detail="Kernel session not found")

        cell = next((c for c in notebook.cells if c.id == cell_id), None)
        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")

        if cell.type != CellType.CODE:
            return cell

        try:
            cell.status = CellStatus.RUNNING
            result = await session.execute(cell.content, timeout)
            
            cell.execution_count = result['execution_count']
            cell.outputs = result['outputs']
            cell.error = result['error']
            cell.status = CellStatus.ERROR if result['error'] else CellStatus.COMPLETE
            cell.executed_at = datetime.utcnow()
            notebook.updated_at = datetime.utcnow()
            
            # Save notebook file
            await self._save_notebook(notebook)
            return cell
            
        except Exception as e:
            cell.status = CellStatus.ERROR
            cell.error = {
                'ename': type(e).__name__,
                'evalue': str(e),
                'traceback': []
            }
            raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")

    async def execute_all_cells(self, notebook_id: str, timeout: int = 30) -> List[NotebookCell]:
        """Execute all code cells in a notebook in order"""
        notebook = self.get_notebook(notebook_id)
        executed_cells = []
        
        for cell in notebook.cells:
            if cell.type == CellType.CODE:
                executed_cell = await self.execute_cell(notebook_id, cell.id, timeout)
                executed_cells.append(executed_cell)
                
                # Stop execution if a cell errors out
                if executed_cell.status == CellStatus.ERROR:
                    break
                    
        return executed_cells

    async def clear_cell_output(self, notebook_id: str, cell_id: str) -> NotebookCell:
        """Clear outputs of a specific cell"""
        notebook = self.get_notebook(notebook_id)
        cell = next((c for c in notebook.cells if c.id == cell_id), None)
        if not cell:
            raise HTTPException(status_code=404, detail="Cell not found")
            
        cell.outputs = []
        cell.execution_count = None
        cell.error = None
        cell.status = CellStatus.IDLE
        
        await self._save_notebook(notebook)
        return cell

    async def clear_all_outputs(self, notebook_id: str) -> Notebook:
        """Clear all cell outputs in a notebook"""
        notebook = self.get_notebook(notebook_id)
        for cell in notebook.cells:
            if cell.type == CellType.CODE:
                cell.outputs = []
                cell.execution_count = None
                cell.error = None
                cell.status = CellStatus.IDLE
                
        await self._save_notebook(notebook)
        return notebook

    async def start_server(self) -> dict:
        """Start Jupyter server and return connection info"""
        # Generate random token for security
        token = secrets.token_hex(32)
        
        # Create jupyter config
        config_dir = Path("/home/scrapybara/.jupyter")
        config_dir.mkdir(parents=True, exist_ok=True)
        
        config = {
            "NotebookApp": {
                "ip": "0.0.0.0",
                "port": self.server_port,
                "token": token,
                "allow_origin": "*",
                "allow_remote_access": True,
                "notebook_dir": str(self.notebook_dir),
                "disable_check_xsrf": True,
                "allow_root": True,
                "open_browser": False,
                "terminado_settings": {"shell_command": ["/bin/bash"]},
                "quit_button": False
            }
        }
        
        config_path = config_dir / "jupyter_notebook_config.json"
        with open(config_path, "w") as f:
            json.dump(config, f)
            
        # Start Jupyter server
        if self.server_process is None or self.server_process.returncode is not None:
            cmd = f"jupyter notebook --config={config_path}"
            self.server_process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for server to start
            await asyncio.sleep(2)
            
        return {
            "url": f"http://0.0.0.0:{self.server_port}",
            "token": token,
            "notebook_dir": str(self.notebook_dir)
        }
        
    async def stop_server(self):
        """Stop the Jupyter server"""
        if self.server_process:
            self.server_process.terminate()
            await self.server_process.wait()
            self.server_process = None

    async def get_notebook_url(self, notebook_id: str) -> str:
        """Get the URL for a specific notebook"""
        notebook = self.get_notebook(notebook_id)
        
        # Ensure server is running
        server_info = await self.start_server()
        
        # Save notebook to file
        await self._save_notebook(notebook)
            
        # Return URL with token
        return f"{server_info['url']}/notebooks/{notebook_id}.ipynb?token={server_info['token']}"

    async def _save_notebook(self, notebook: Notebook):
        """Save notebook to file in Jupyter format"""
        notebook_data = self._to_jupyter_format(notebook)
        notebook_path = self.notebook_dir / f"{notebook.id}.ipynb"
        
        # Directly write the file without creating a nested coroutine
        def write_file():
            with open(notebook_path, "w") as f:
                json.dump(notebook_data, f, indent=2)
                
        # Run the file writing in an executor
        await asyncio.get_event_loop().run_in_executor(None, write_file)

    async def load_notebook(self, notebook_id: str) -> Optional[Notebook]:
        """Load notebook from file"""
        notebook_path = self.notebook_dir / f"{notebook_id}.ipynb"
        
        if not notebook_path.exists():
            return None
            
        # Directly read the file without creating a nested coroutine
        def read_file():
            with open(notebook_path, "r") as f:
                return json.load(f)
                
        notebook_data = await asyncio.get_event_loop().run_in_executor(None, read_file)
        return self._from_jupyter_format(notebook_data, notebook_id)

    def _to_jupyter_format(self, notebook: Notebook) -> Dict[str, Any]:
        """Convert notebook to Jupyter format"""
        cells = []
        for cell in notebook.cells:
            jupyter_cell = {
                "cell_type": cell.type,
                "metadata": cell.metadata,
                "source": cell.content.splitlines(True),
            }
            
            if cell.type == CellType.CODE:
                jupyter_cell["outputs"] = cell.outputs
                jupyter_cell["execution_count"] = cell.execution_count
                
            cells.append(jupyter_cell)
            
        return {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {
                    "name": notebook.kernel_name,
                    "language": notebook.kernel_name,
                    "display_name": notebook.kernel_name
                },
                **notebook.metadata
            },
            "cells": cells
        }

    def _from_jupyter_format(self, data: Dict[str, Any], notebook_id: str) -> Notebook:
        """Convert Jupyter format to notebook"""
        kernel_name = data.get("metadata", {}).get("kernelspec", {}).get("name", "python3")
        
        cells = []
        for cell_data in data.get("cells", []):
            cell = NotebookCell(
                type=CellType(cell_data["cell_type"]),
                content="".join(cell_data.get("source", [])),
                metadata=cell_data.get("metadata", {}),
                outputs=cell_data.get("outputs", []) if cell_data["cell_type"] == "code" else [],
                execution_count=cell_data.get("execution_count") if cell_data["cell_type"] == "code" else None
            )
            cells.append(cell)
            
        return Notebook(
            id=notebook_id,
            name=f"Notebook {notebook_id}",
            kernel_name=kernel_name,
            cells=cells,
            metadata=data.get("metadata", {})
        )

    async def execute_code(self, code: str, kernel_name: str = "python3", timeout: int = 30) -> Dict[str, Any]:
        """
        Execute code in a temporary kernel session and return the result
        """
        # Create temporary kernel session
        temp_session = KernelSession(kernel_name)
        try:
            # Execute the code
            result = await temp_session.execute(code, timeout)
            return {
                'execution_count': result['execution_count'],
                'outputs': result['outputs'],
                'error': result['error']
            }
        finally:
            # Always clean up the temporary kernel
            temp_session.shutdown()

# Initialize the service instance
notebook_service = NotebookService()

# Add cleanup on shutdown
import atexit

def cleanup_notebooks():
    for session in notebook_service.kernel_sessions.values():
        session.shutdown()
    
    if notebook_service.server_process:
        notebook_service.server_process.terminate()

atexit.register(cleanup_notebooks)
