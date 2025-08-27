
import os
import logging
import asyncio
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator

from openstack_client_requests import OpenStackRequestsClient, OpenStackError

# ---------- Logging ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mcp-openstack-requests")

# ---------- MCP Server ----------
mcp = FastMCP(name="mcp-openstack-requests")

class GetServerByIdInput(BaseModel):
    instance_id: str = Field(..., description="OpenStack server (instance) ID to fetch")
    project_id: Optional[str] = Field(None, description="Project/tenant ID to scope the token (optional)")
    # region is unused in the requests version that uses fixed host:ports, but kept for forward-compat
    region: Optional[str] = Field(None, description="Region name (optional; ignored in requests-based client)")
    
    @field_validator('instance_id', mode='before')
    def _strip_and_check(cls, v):
        if not isinstance(v, str):
            raise TypeError('instance_id must be a string')
        v = v.strip()
        if not v:
            raise ValueError('instance_id must not be empty')
        return v

@mcp.tool(
    name="get_server_by_id",
    description=(
        "Retrieve OpenStack VM details by instance_id. "
        "Inputs: instance_id (required), project_id (optional). "
        "Returns normalized JSON with server status, networking (IPs, allowed pairs), volumes, and metadata."
    ),
)
async def get_server_by_id(params: GetServerByIdInput) -> Dict[str, Any]:
    """
    MCP tool handler. Calls OpenStack via requests.
    wrapped via asyncio.to_thread so the MCP server remains responsive.
    """
    # Build client using the same envs as your verified script
    client = OpenStackRequestsClient(
        host=os.getenv("OS_HOST", "127.0.0.1"),
        username=os.getenv("OS_USERNAME"),
        password=os.getenv("OS_PASSWORD"),
        project_id=params.project_id or os.getenv("OS_PROJECT_ID"),
        user_domain=os.getenv("OS_USER_DOMAIN_NAME", "Default"),
        verify=(os.getenv("OS_VERIFY_SSL", "false").lower() != "false"),
    )

    try:
        # Run the blocking call in a worker thread
        result = await asyncio.to_thread(client.get_server_composite, params.instance_id)
        return result
    except OpenStackError as e:
        logger.exception("OpenStackError while fetching server %s", params.instance_id)
        return {
            "error": {
                "type": "OpenStackError",
                "message": str(e),
                "http_status": e.http_status,
                "details": e.details,
            }
        }
    except Exception as e:
        logger.exception("Unexpected error while fetching server %s", params.instance_id)
        return {
            "error": {
                "type": "UnexpectedError",
                "message": str(e),
                "http_status": None,
                "details": None,
            }
        }

if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8083"))
    mcp.settings.host = host
    mcp.settings.port = port
    logger.info("Starting MCP OpenStack (requests) on %s:%d (transport=SSE)", host, port)
    mcp.run(transport="sse")
