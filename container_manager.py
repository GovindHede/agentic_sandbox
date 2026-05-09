import os
import time
import shutil
import tempfile
import docker
import requests
from typing import Dict, Any

class SandboxManager:
    """
    Manages the lifecycle of isolated Docker containers for executing untrusted Python code.
    """
    def __init__(self) -> None:
        """Initializes the SandboxManager and ensures the required Docker image is available."""
        self.client = docker.from_env()
        self.image_name = "python:3.11-slim"
        self._ensure_image_exists()

    def _ensure_image_exists(self) -> None:
        """
        Pulls the required Docker image if it is not already present on the host.
        """
        try:
            self.client.images.get(self.image_name)
        except docker.errors.ImageNotFound:
            print(f"Image {self.image_name} not found locally. Pulling...")
            self.client.images.pull(self.image_name)

    def execute_code(self, code: str) -> Dict[str, Any]:
        """
        Executes the provided Python code in a securely isolated Docker container.
        
        Args:
            code (str): The untrusted Python code to execute.
            
        Returns:
            Dict[str, Any]: A dictionary containing:
                - status (str): 'success', 'timeout', or 'error'
                - stdout (str): Standard output logs from the execution
                - stderr (str): Standard error logs from the execution
                - execution_time (float): The total execution time in seconds
        """
        # Create a temporary directory on the host to store the code
        temp_dir = tempfile.mkdtemp()
        code_file_path = os.path.join(temp_dir, "script.py")
        
        with open(code_file_path, "w", encoding="utf-8") as f:
            f.write(code)

        container = None
        start_time = time.time()
        
        try:
            # Run the container with strict resource limits and offline mode.
            # Using detach=True allows us to gracefully manage the timeout logic.
            container = self.client.containers.run(
                image=self.image_name,
                command=["python", "/app/script.py"],
                volumes={temp_dir: {'bind': '/app', 'mode': 'ro'}},
                working_dir="/app",
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                network_mode="none",
                detach=True,
            )

            # Wait for the container to finish with a strict 15-second timeout
            try:
                result = container.wait(timeout=15)
                status_code = result.get("StatusCode", 1)
                status = "success" if status_code == 0 else "error"
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                # If the docker wait request times out, it was taking longer than 15 seconds
                return {
                    "status": "timeout",
                    "stdout": "",
                    "stderr": "Execution timed out after 15 seconds.",
                    "execution_time": time.time() - start_time
                }

            # Fetch the logs (stdout and stderr separated)
            stdout_logs = container.logs(stdout=True, stderr=False).decode("utf-8")
            stderr_logs = container.logs(stdout=False, stderr=True).decode("utf-8")
            
            return {
                "status": status,
                "stdout": stdout_logs,
                "stderr": stderr_logs,
                "execution_time": time.time() - start_time
            }

        except Exception as e:
            return {
                "status": "error",
                "stdout": "",
                "stderr": f"Unexpected execution error: {str(e)}",
                "execution_time": time.time() - start_time
            }
        finally:
            # Cleanup: Container and temporary files MUST be destroyed immediately.
            # Using robust try...finally blocks ensures that even if wait() throws
            # an exception, we leave no dangling resources on the host system.
            if container is not None:
                try:
                    # Fetching it fresh to ensure we forcefully kill the current state.
                    self.client.containers.get(container.id).kill()
                except docker.errors.APIError:
                    pass # Container is likely already stopped
                    
                try:
                    # Remove the container including volumes
                    container.remove(v=True, force=True)
                except docker.errors.APIError:
                    pass
            
            # Clean up the temporary directory on the host
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
