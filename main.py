from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any, Union
import json
import asyncio
import os
import sys
import logging
import subprocess
import time
import random
import string
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("gmail-mcp-api")

# Print debug messages to stderr for immediate feedback
def debug_print(message):
    print(f"DEBUG: {message}", file=sys.stderr)
    logger.info(message)

# Global MCP server process
mcp_process = None
request_lock = asyncio.Lock()
pending_requests = {}

app = FastAPI(
    title="Gmail MCP API",
    description="A FastAPI wrapper for Gmail MCP server",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the path to the MCP server
SCRIPT_DIR = Path(__file__).parent.absolute()
MCP_SERVER_PATH = os.environ.get(
    "MCP_SERVER_PATH", 
    r"C:\Users\ujjwa\Desktop\Aiva\MCP servers\gmail 2\gmail-mcp\dist\index.js"
)

debug_print(f"MCP Server Path: {MCP_SERVER_PATH}")
debug_print(f"MCP Server Path exists: {os.path.exists(MCP_SERVER_PATH)}")

# Models
class ToolRequest(BaseModel):
    tool: str
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)

class ToolResponse(BaseModel):
    result: Union[Dict[str, Any], List[Any], str]

# Create MCP server process
async def start_mcp_server():
    global mcp_process
    
    debug_print("Starting MCP server process...")
    
    # Start the MCP server process
    mcp_process = await asyncio.create_subprocess_exec(
        "node", MCP_SERVER_PATH,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    debug_print(f"MCP server process started with PID: {mcp_process.pid}")
    
    # Start background task to read stdout
    asyncio.create_task(read_mcp_stdout())
    # Start background task to read stderr
    asyncio.create_task(read_mcp_stderr())

# Read stdout from MCP server
async def read_mcp_stdout():
    global mcp_process, pending_requests
    
    debug_print("Started stdout reader task")
    
    while True:
        try:
            # Read a line from stdout
            line = await mcp_process.stdout.readline()
            
            if not line:
                debug_print("MCP server stdout closed")
                break
                
            line_str = line.decode().strip()
            debug_print(f"MCP stdout: {line_str}")
            
            # Try to parse as JSON
            try:
                response = json.loads(line_str)
                request_id = response.get("id")
                
                if request_id and request_id in pending_requests:
                    debug_print(f"Found matching request ID: {request_id}")
                    # Set the result for the pending request
                    pending_requests[request_id]["response"] = response
                    # Set the event to signal the request is complete
                    pending_requests[request_id]["event"].set()
            except json.JSONDecodeError:
                debug_print(f"Failed to parse JSON: {line_str}")
        except Exception as e:
            debug_print(f"Error reading stdout: {str(e)}")
            await asyncio.sleep(0.1)

# Read stderr from MCP server
async def read_mcp_stderr():
    global mcp_process
    
    debug_print("Started stderr reader task")
    
    while True:
        try:
            # Read a line from stderr
            line = await mcp_process.stderr.readline()
            
            if not line:
                debug_print("MCP server stderr closed")
                break
                
            line_str = line.decode().strip()
            debug_print(f"MCP stderr: {line_str}")
        except Exception as e:
            debug_print(f"Error reading stderr: {str(e)}")
            await asyncio.sleep(0.1)

# Generate a unique request ID
def generate_request_id():
    timestamp = int(time.time() * 1000)
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return f"{timestamp}-{random_str}"

# Home page with usage information
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <html>
      <head>
        <title>Gmail MCP FastAPI Server</title>
        <style>
          body { font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; max-width: 800px; margin: 0 auto; }
          h1 { color: #1a73e8; }
          pre { background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }
          code { font-family: monospace; }
        </style>
      </head>
      <body>
        <h1>Gmail MCP FastAPI Server</h1>
        <p>This server exposes the Gmail Model Context Protocol (MCP) over HTTP using FastAPI.</p>
        
        <h2>API Endpoints</h2>
        <ul>
          <li><code>GET /api/tools</code> - List all available tools</li>
          <li><code>POST /api/gmail</code> - Call a Gmail MCP tool</li>
          <li><code>GET /health</code> - Health check endpoint</li>
        </ul>
        
        <h2>Example Usage</h2>
        <pre>
curl -X POST http://localhost:8000/api/gmail \\
  -H "Content-Type: application/json" \\
  -d '{"tool": "list_labels", "params": {}}'</pre>
        
        <p>To explore the API documentation, visit <a href="/docs">/docs</a> or <a href="/redoc">/redoc</a>.</p>
      </body>
    </html>
    """

# Health check endpoint
@app.get("/health")
async def health_check():
    global mcp_process
    
    if mcp_process is None or mcp_process.returncode is not None:
        return {"status": "error", "message": "MCP server process not running"}
        
    return {"status": "ok", "mcp_pid": mcp_process.pid}

# List all available tools
@app.get("/api/tools", response_model=Dict[str, List[str]])
async def list_tools():
    # This is a static list of all available tools from the MCP
    tools = [
        'create_draft', 'delete_draft', 'get_draft', 'list_drafts', 'send_draft', 'update_draft',
        'create_label', 'delete_label', 'get_label', 'list_labels', 'patch_label', 'update_label',
        'batch_delete_messages', 'batch_modify_messages', 'delete_message', 'get_message', 
        'list_messages', 'modify_message', 'send_message', 'trash_message', 'untrash_message',
        'get_attachment', 'delete_thread', 'get_thread', 'list_threads', 'modify_thread',
        'trash_thread', 'untrash_thread',
        'get_auto_forwarding', 'get_imap', 'get_language', 'get_pop', 'get_vacation',
        'update_auto_forwarding', 'update_imap', 'update_language', 'update_pop', 'update_vacation',
        'add_delegate', 'remove_delegate', 'get_delegate', 'list_delegates',
        'create_filter', 'delete_filter', 'get_filter', 'list_filters',
        'create_forwarding_address', 'delete_forwarding_address', 'get_forwarding_address', 'list_forwarding_addresses',
        'create_send_as', 'delete_send_as', 'get_send_as', 'list_send_as', 'patch_send_as',
        'update_send_as', 'verify_send_as',
        'delete_smime_info', 'get_smime_info', 'insert_smime_info', 'list_smime_info', 'set_default_smime_info',
        'get_profile', 'watch_mailbox', 'stop_mail_watch'
    ]
    
    return {"tools": tools}

async def run_mcp_command(tool: str, params: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """Execute an MCP tool and return the results."""
    global mcp_process, pending_requests, request_lock
    
    if mcp_process is None or mcp_process.returncode is not None:
        debug_print("MCP server process not running, starting...")
        await start_mcp_server()
    
    # Generate a unique request ID
    request_id = generate_request_id()
    debug_print(f"Generated request ID: {request_id}")
    
    # Create an event for this request
    event = asyncio.Event()
    
    # Store the request in pending_requests
    pending_requests[request_id] = {
        "event": event,
        "response": None
    }
    
    # Try all formats sequentially until one works
    formats = [
        # Format 1: Direct method call with tool name
        {
            "id": request_id,
            "jsonrpc": "2.0",
            "method": tool,
            "params": params or {}
        },
        # Format 2: mcp.runTool
        {
            "id": request_id,
            "jsonrpc": "2.0",
            "method": "mcp.runTool",
            "params": {
                "name": tool,
                "arguments": params or {}
            }
        },
        # Format 3: Using the SDK format
        {
            "id": request_id,
            "jsonrpc": "2.0",
            "method": "runTool",
            "params": {
                "name": tool,
                "input": params or {}
            }
        }
    ]
    
    # Try each format
    for i, request_format in enumerate(formats):
        debug_print(f"Trying format {i+1}: {json.dumps(request_format, indent=2)}")
        
        # Serialize the request
        request_json = json.dumps(request_format) + "\n"
        
        try:
            # Acquire lock to ensure only one request is sent at a time
            async with request_lock:
                # Send the request to the MCP server
                debug_print(f"Sending request to MCP server: {request_json}")
                mcp_process.stdin.write(request_json.encode())
                await mcp_process.stdin.drain()
            
            # Wait for the response with timeout
            try:
                await asyncio.wait_for(event.wait(), timeout)
            except asyncio.TimeoutError:
                debug_print(f"Timeout waiting for response to format {i+1}")
                continue
            
            # Get the response
            response = pending_requests[request_id]["response"]
            debug_print(f"Received response: {json.dumps(response, indent=2)}")
            
            # Check for errors
            if "error" in response:
                debug_print(f"Error in response: {response['error']}")
                if i < len(formats) - 1:
                    debug_print(f"Format {i+1} failed, trying next format")
                    # Reset the event for the next attempt
                    event.clear()
                    continue
                else:
                    # Last format, return the error
                    raise HTTPException(status_code=500, detail=response["error"])
            
            # Process the result
            if "result" in response:
                debug_print("Found result in response")
                result = response["result"]
                
                # Handle MCP content format
                if isinstance(result, dict) and "content" in result:
                    debug_print("Result contains content field")
                    for item in result["content"]:
                        if item.get("type") == "text":
                            debug_print(f"Found text content")
                            try:
                                parsed_text = json.loads(item["text"])
                                debug_print("Successfully parsed text content as JSON")
                                return {"result": parsed_text}
                            except json.JSONDecodeError:
                                debug_print("Text content is not JSON, returning as is")
                                return {"result": item["text"]}
                
                debug_print("Returning result directly")
                return {"result": result}
            
            # No result found
            raise HTTPException(status_code=500, detail="No result in response")
        except Exception as e:
            if i < len(formats) - 1:
                debug_print(f"Error with format {i+1}: {str(e)}, trying next format")
                continue
            else:
                debug_print(f"All formats failed: {str(e)}")
                raise HTTPException(status_code=500, detail=str(e))
    
    # Clean up
    del pending_requests[request_id]
    
    # If we get here, all formats failed
    raise HTTPException(status_code=500, detail="All JSON-RPC format attempts failed")

@app.post("/api/gmail", response_model=ToolResponse)
async def call_gmail_tool(request: ToolRequest):
    """Call a Gmail MCP tool with the provided parameters."""
    debug_print(f"Received request for tool: {request.tool}")
    debug_print(f"Parameters: {json.dumps(request.params)}")
    
    try:
        result = await run_mcp_command(request.tool, request.params)
        return result
    except Exception as e:
        debug_print(f"Error executing tool: {str(e)}")
        raise

# Startup event
@app.on_event("startup")
async def startup_event():
    debug_print("Starting up FastAPI server...")
    await start_mcp_server()

# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    global mcp_process
    
    debug_print("Shutting down FastAPI server...")
    
    if mcp_process and mcp_process.returncode is None:
        debug_print(f"Terminating MCP server process (PID: {mcp_process.pid})...")
        try:
            mcp_process.terminate()
            await asyncio.wait_for(mcp_process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            debug_print("MCP server process did not terminate, killing...")
            mcp_process.kill()

if __name__ == "__main__":
    import uvicorn
    debug_print("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)