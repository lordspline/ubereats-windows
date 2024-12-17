from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import asyncio
import win32gui
import win32con
from fastapi.middleware.cors import CORSMiddleware

from .tools import (
    ComputerTool, 
    BashTool,
    EditTool,
    ToolResult,
    ToolError
)
from .tools.computer import Action
from .tools.edit import Command
from .services.browser import browser_manager
from .services.filesystem import FilesystemService, EnvironmentService
from .services.notebook import (
    notebook_service,
    CellType,
    NotebookCell,
    Notebook,
    KernelInfo
)

async def wait_for_session(timeout=300):  # 5 minute timeout
    """Wait for an active desktop session"""
    start_time = asyncio.get_event_loop().time()
    while True:
        try:
            desktop = win32gui.GetDesktopWindow()
            dc = win32gui.GetDC(desktop)
            if dc != 0:
                win32gui.ReleaseDC(desktop, dc)
                return True
        except Exception:
            pass
        
        if asyncio.get_event_loop().time() - start_time > timeout:
            raise Exception("Timeout waiting for desktop session")
            
        await asyncio.sleep(1)

app = FastAPI(
    title="Computer Use API",
    description="REST API for computer use tools",
    version="1.0.0"
)

# Add CORS middleware if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Wait for desktop session on startup"""
    try:
        await wait_for_session()
    except Exception as e:
        print(f"Warning: Failed to detect desktop session: {e}")
        # Optionally exit if you want to enforce desktop session requirement
        # import sys
        # sys.exit(1)

# Initialize tools
computer_tool = ComputerTool()
bash_tool = BashTool()
edit_tool = EditTool()

files_service = FilesystemService()
env_service = EnvironmentService()

class ComputerRequest(BaseModel):
    action: Action
    coordinate: Optional[List[int]] = None
    text: Optional[str] = None

class BashRequest(BaseModel):
    command: Optional[str] = None
    restart: bool = False

class EditRequest(BaseModel):
    command: Command
    path: str
    file_text: Optional[str] = None
    view_range: Optional[List[int]] = None
    old_str: Optional[str] = None
    new_str: Optional[str] = None
    insert_line: Optional[int] = None

class ToolResponse(BaseModel):
    output: Optional[str] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None
    system: Optional[str] = None

class CreateNotebookRequest(BaseModel):
    name: str
    kernel_name: str

class AddCellRequest(BaseModel):
    type: CellType
    content: str
    metadata: Optional[Dict[str, Any]] = None

class ExecuteCellRequest(BaseModel):
    timeout: Optional[int] = 30

class CodeExecuteRequest(BaseModel):
    code: str
    kernel_name: str = "python3"
    timeout: Optional[int] = 30

@app.post("/computer", response_model=ToolResponse)
async def computer_action(request: ComputerRequest):
    try:
        result = await computer_tool(**request.model_dump(exclude_none=True))
        return _tool_result_to_response(result)
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/bash", response_model=ToolResponse)
async def bash_action(request: BashRequest):
    try:
        result = await bash_tool(**request.model_dump(exclude_none=True))
        return _tool_result_to_response(result)
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/edit", response_model=ToolResponse)
async def edit_action(request: EditRequest):
    try:
        result = await edit_tool(
            command=request.command,
            path=request.path,
            **{k: v for k, v in request.model_dump().items() 
               if k not in ['command', 'path'] and v is not None}
        )
        return _tool_result_to_response(result)
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/screenshot", response_model=ToolResponse)
async def get_screenshot():
    try:
        result = await computer_tool(action="screenshot")
        return _tool_result_to_response(result)
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/status")
async def get_status():
    return {"status": "ok"}

@app.post("/browser/start")
async def start_browser():
    """Start browser and return CDP endpoint URL."""
    try:
        cdp_endpoint = await browser_manager.start_browser()
        return {
            "status": "Browser started successfully",
            "cdp_endpoint": cdp_endpoint
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/browser/stop")
async def stop_browser():
    """Stop the browser instance."""
    try:
        await browser_manager.stop_browser()
        return {"status": "Browser stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/browser/status")
async def get_browser_status():
    """Get current browser status and CDP endpoint if running."""
    cdp_endpoint = browser_manager.cdp_endpoint
    return {
        "status": "running" if cdp_endpoint else "stopped",
        "cdp_endpoint": cdp_endpoint
    }

@app.get("/files/read")
async def read_file(path: str, encoding: Optional[str] = 'utf-8'):
    """Read a file from the filesystem"""
    content = await files_service.read(path, encoding)
    return {"content": content if isinstance(content, str) else content.decode(encoding or 'utf-8')}

@app.post("/files/write")
async def write_file(request: Dict[str, str]):
    """Write content to a file"""
    path = request.get("path")
    content = request.get("content")
    encoding = request.get("encoding", "utf-8")
    
    if not path or content is None:
        raise HTTPException(status_code=400, detail="Path and content are required")
        
    await files_service.write(path, content, encoding)
    return {"status": "success", "message": f"File written to {path}"}

@app.post("/files/upload")
async def upload_file(request: Dict[str, str]):
    """Upload a base64 encoded file"""
    path = request.get("path")
    content = request.get("content")
    
    if not path or not content:
        raise HTTPException(status_code=400, detail="Path and content are required")
        
    await files_service.upload(path, content)
    return {"status": "success", "message": f"File uploaded to {path}"}

@app.get("/files/download")
async def download_file(path: str):
    """Download a file as base64 encoded content"""
    content = await files_service.download(path)
    return {"content": content}

@app.post("/env")
async def set_environment_variables(request: Dict[str, Dict[str, str]]):
    """Set environment variables"""
    variables = request.get("variables")
    if not variables:
        raise HTTPException(status_code=400, detail="Variables are required")
        
    await env_service.set_env(variables)
    return {"status": "success", "message": "Environment variables set"}

@app.get("/env")
async def get_environment_variables():
    """Get all environment variables"""
    variables = await env_service.get_env()
    return {"variables": variables}

@app.post("/env/delete")
async def delete_environment_variables(request: Dict[str, List[str]]):
    """Delete specified environment variables"""
    keys = request.get("keys")
    if not keys:
        raise HTTPException(status_code=400, detail="Keys are required")
        
    await env_service.delete_env(keys)
    return {"status": "success", "message": "Environment variables deleted"}

@app.get("/notebook/kernels", response_model=List[KernelInfo])
async def list_kernels():
    """List available notebook kernels"""
    return notebook_service.list_kernels()

@app.post("/notebook/create", response_model=Notebook)
async def create_notebook(request: CreateNotebookRequest):
    """Create a new notebook"""
    return await notebook_service.create_notebook(request.name, request.kernel_name)

@app.get("/notebook/{notebook_id}", response_model=Notebook)
async def get_notebook(notebook_id: str):
    """Get a notebook by ID"""
    return notebook_service.get_notebook(notebook_id)

@app.post("/notebook/{notebook_id}/delete")
async def delete_notebook(notebook_id: str):
    """Delete a notebook"""
    await notebook_service.delete_notebook(notebook_id)
    return {"status": "success"}

@app.post("/notebook/{notebook_id}/cell", response_model=NotebookCell)
async def add_cell(notebook_id: str, request: AddCellRequest):
    """Add a new cell to a notebook"""
    return await notebook_service.add_cell(
        notebook_id,
        request.type,
        request.content,
        request.metadata
    )

@app.post("/notebook/{notebook_id}/cell/{cell_id}/execute", response_model=NotebookCell)
async def execute_cell(
    notebook_id: str,
    cell_id: str,
    request: Optional[ExecuteCellRequest] = None
):
    """Execute a specific cell"""
    timeout = request.timeout if request else 30
    return await notebook_service.execute_cell(
        notebook_id,
        cell_id,
        timeout
    )

@app.post("/notebook/{notebook_id}/execute", response_model=List[NotebookCell])
async def execute_all_cells(
    notebook_id: str,
    request: Optional[ExecuteCellRequest] = None
):
    """Execute all cells in a notebook"""
    timeout = request.timeout if request else 30
    return await notebook_service.execute_all_cells(
        notebook_id,
        timeout
    )

@app.post("/notebook/{notebook_id}/cell/{cell_id}/clear", response_model=NotebookCell)
async def clear_cell_output(notebook_id: str, cell_id: str):
    """Clear outputs of a specific cell"""
    return await notebook_service.clear_cell_output(notebook_id, cell_id)

@app.post("/notebook/{notebook_id}/clear", response_model=Notebook)
async def clear_all_outputs(notebook_id: str):
    """Clear all cell outputs in a notebook"""
    return await notebook_service.clear_all_outputs(notebook_id)

@app.post("/notebook/server/start")
async def start_jupyter_server():
    """Start Jupyter server and get connection info"""
    return await notebook_service.start_server()

@app.post("/notebook/server/stop")
async def stop_jupyter_server():
    """Stop Jupyter server"""
    await notebook_service.stop_server()
    return {"status": "stopped"}

@app.get("/notebook/{notebook_id}/url")
async def get_notebook_url(notebook_id: str):
    """Get URL to open notebook in browser"""
    url = await notebook_service.get_notebook_url(notebook_id)
    return {"url": url}

@app.post("/code/execute")
async def execute_code(request: CodeExecuteRequest):
    """
    Execute code in specified kernel without creating a notebook
    """
    try:
        result = await notebook_service.execute_code(
            code=request.code,
            kernel_name=request.kernel_name,
            timeout=request.timeout
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _tool_result_to_response(result: ToolResult) -> Dict[str, Any]:
    return {
        "output": result.output,
        "error": result.error,
        "base64_image": result.base64_image,
        "system": result.system
    }
