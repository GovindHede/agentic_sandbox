import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any

from core.container_manager import SandboxManager

# Initialize the FastAPI application
app = FastAPI(
    title="Agentic Sandbox API",
    description="An ephemeral, isolated execution environment for testing autonomous AI agents.",
    version="1.0.0"
)

# Initialize the manager globally so we can reuse the Docker client and pull the image once
try:
    sandbox_manager = SandboxManager()
except Exception as e:
    logging.error(f"Failed to initialize SandboxManager: {e}")
    sandbox_manager = None

class AgentExecutionRequest(BaseModel):
    """Schema for the incoming agent execution request."""
    code: str = Field(..., description="The Python code string to execute in the sandbox.")

class ExecutionResponse(BaseModel):
    """Schema for the outgoing sandbox execution results."""
    status: str = Field(..., description="The execution status: 'success', 'timeout', or 'error'.")
    stdout: str = Field(..., description="Standard output logs from the container execution.")
    stderr: str = Field(..., description="Standard error logs from the container execution.")
    execution_time: float = Field(..., description="Total execution time in seconds.")

@app.post("/api/v1/sandbox/run", response_model=ExecutionResponse)
def run_code(request: AgentExecutionRequest) -> Dict[str, Any]:
    """
    Executes the provided Python code securely in an isolated Docker container.
    
    Note: We are deliberately using a standard synchronous endpoint (`def` instead of `async def`).
    FastAPI handles standard sync functions by executing them in a separate external threadpool.
    This safely prevents the blocking I/O bound Docker operations from hanging the main async event loop.
    """
    if sandbox_manager is None:
        raise HTTPException(
            status_code=500,
            detail="SandboxManager is not initialized properly. Please check your Docker daemon."
        )

    try:
        # Passes the code string to the docker manager and blocks safely in a thread
        result = sandbox_manager.execute_code(request.code)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected API error occurred: {str(e)}"
        )
