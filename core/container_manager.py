import os
import time
import shutil
import tempfile
import docker
import requests
from typing import Dict, Any

# Path to the mitmproxy CA certificate on the host machine.
# This is auto-generated the first time mitmdump runs.
MITMPROXY_CERT_PATH: str = os.path.join(
    os.path.expanduser("~"), ".mitmproxy", "mitmproxy-ca-cert.pem"
)

# Proxy endpoint: containers reach the host via the special Docker DNS name.
# 'host-gateway' maps to the host's IP on Linux; on Docker Desktop (Win/Mac)
# host.docker.internal is resolved automatically, but extra_hosts ensures
# cross-platform parity.
PROXY_HOST: str = "host.docker.internal"
PROXY_PORT: str = "8080"
PROXY_URL: str = f"http://{PROXY_HOST}:{PROXY_PORT}"

# Path where the mitmproxy cert will be mounted inside the container
CONTAINER_CERT_PATH: str = "/tmp/mitmproxy-ca-cert.pem"


class SandboxManager:
    """
    Manages the lifecycle of isolated Docker containers for executing untrusted Python code.
    All outbound HTTP/HTTPS traffic from the container is routed through the local
    mitmproxy instance, which intercepts requests and returns AI-generated mock responses.
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

    @staticmethod
    def _validate_cert_exists() -> None:
        """
        Validates that the mitmproxy CA certificate exists on the host.
        This cert is required for the container to trust HTTPS traffic
        intercepted by the proxy. It is auto-generated the first time
        mitmdump runs.

        Raises:
            FileNotFoundError: If the certificate file is missing.
        """
        if not os.path.isfile(MITMPROXY_CERT_PATH):
            raise FileNotFoundError(
                f"mitmproxy CA certificate not found at: {MITMPROXY_CERT_PATH}\n"
                f"Please run 'mitmdump' once on the host to auto-generate it, "
                f"then try again."
            )

    def execute_code(self, code: str) -> Dict[str, Any]:
        """
        Executes the provided Python code in a securely isolated Docker container.
        All outbound HTTP/HTTPS traffic is routed through the mitmproxy on the host.

        Args:
            code (str): The untrusted Python code to execute.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - status (str): 'success', 'timeout', or 'error'
                - stdout (str): Standard output logs from the execution
                - stderr (str): Standard error logs from the execution
                - execution_time (float): The total execution time in seconds
        """
        # Validate the mitmproxy cert exists before doing any work
        self._validate_cert_exists()

        # Create a temporary directory on the host to store the code
        temp_dir = tempfile.mkdtemp()
        code_file_path = os.path.join(temp_dir, "script.py")

        with open(code_file_path, "w", encoding="utf-8") as f:
            f.write(code)

        container = None
        start_time = time.time()

        try:
            # --- Volume Mounts ---
            # 1. Agent code directory -> /app (read-only)
            # 2. mitmproxy CA cert  -> /tmp/mitmproxy-ca-cert.pem (read-only)
            volumes: Dict[str, Dict[str, str]] = {
                temp_dir: {'bind': '/app', 'mode': 'ro'},
                MITMPROXY_CERT_PATH: {'bind': CONTAINER_CERT_PATH, 'mode': 'ro'},
            }

            # --- Environment Variables ---
            # HTTP_PROXY / HTTPS_PROXY: Routes all outbound traffic through mitmproxy.
            # REQUESTS_CA_BUNDLE: Tells Python's requests/urllib3 to trust the
            #   mitmproxy CA cert so intercepted HTTPS connections don't fail
            #   with SSL verification errors.
            # NOTE: Python's urllib on Linux reads LOWERCASE env vars (http_proxy),
            #   while requests/pip use UPPERCASE. We set BOTH for full compatibility.
            #   NO_PROXY prevents mitmproxy from intercepting pip package downloads.
            environment: Dict[str, str] = {
                "HTTP_PROXY": PROXY_URL,
                "HTTPS_PROXY": PROXY_URL,
                "http_proxy": PROXY_URL,
                "https_proxy": PROXY_URL,
                "no_proxy": "pypi.org,files.pythonhosted.org,pypi.python.org",
                "NO_PROXY": "pypi.org,files.pythonhosted.org,pypi.python.org",
                "REQUESTS_CA_BUNDLE": CONTAINER_CERT_PATH,
                "SSL_CERT_FILE": CONTAINER_CERT_PATH,
            }

            # Run the container with strict resource limits.
            # Using detach=True allows us to gracefully manage the timeout logic.
            container = self.client.containers.run(
                image=self.image_name,
                command=["/bin/sh", "-c", "HTTP_PROXY='' HTTPS_PROXY='' http_proxy='' https_proxy='' REQUESTS_CA_BUNDLE='' SSL_CERT_FILE='' pip install requests && python /app/script.py"],
                volumes=volumes,
                environment=environment,
                working_dir="/app",
                # --- Resource Limits (unchanged from Phase 1) ---
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                # --- Networking (Phase 3) ---
                # Removed network_mode="none" so the container can reach the proxy.
                # extra_hosts maps the Docker DNS name 'host.docker.internal' to
                # the host's gateway IP, ensuring Linux/Mac/Win compatibility.
                extra_hosts={'host.docker.internal': 'host-gateway'},
                detach=True,
            )

            # Wait for the container to finish with a strict 15-second timeout
            try:
                result = container.wait(timeout=30)
                status_code = result.get("StatusCode", 1)
                status = "success" if status_code == 0 else "error"
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                # If the docker wait request times out, it was taking longer than 30 seconds
                return {
                    "status": "timeout",
                    "stdout": "",
                    "stderr": "Execution timed out after 30 seconds.",
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
                    pass  # Container is likely already stopped

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
