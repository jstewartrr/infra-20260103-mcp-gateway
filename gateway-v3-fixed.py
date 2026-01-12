"""
Sovereign Mind MCP Gateway v3.0.1 - With Snowflake Redundant Support
====================================================================
Fixed version that loads Snowflake backend from environment variables
"""

import os
import json
import asyncio
import httpx
import uuid
from flask import Flask, request, jsonify, Response
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# =============================================================================
# BACKEND MCP SERVER CONFIGURATION
# Load from environment variables - matches Gateway V3 deployment pattern
# =============================================================================

def load_backends_from_env():
    """Dynamically load backend MCPs from environment variables"""
    backends = {}

    # Define known backends with their expected env var names
    backend_configs = {
        "m365": {"env_var": "M365_MCP_URL", "prefix": "m365", "description": "Microsoft 365 (Email, Calendar, Users)"},
        "asana": {"env_var": "ASANA_MCP_URL", "prefix": "asana", "description": "Asana project management"},
        "github": {"env_var": "GITHUB_MCP_URL", "prefix": "github", "description": "GitHub repositories"},
        "dealcloud": {"env_var": "DEALCLOUD_MCP_URL", "prefix": "dealcloud", "description": "DealCloud CRM"},
        "dropbox": {"env_var": "DROPBOX_MCP_URL", "prefix": "dropbox", "description": "Dropbox file storage"},
        "make": {"env_var": "MAKE_MCP_URL", "prefix": "make", "description": "Make.com automation", "transport": "sse"},
        "elevenlabs": {"env_var": "ELEVENLABS_MCP_URL", "prefix": "elevenlabs", "description": "ElevenLabs voice agents"},
        "simli": {"env_var": "SIMLI_MCP_URL", "prefix": "simli", "description": "Simli visual avatars"},
        "gemini": {"env_var": "GEMINI_MCP_URL", "prefix": "gemini", "description": "Google Gemini AI"},
        "figma": {"env_var": "FIGMA_MCP_URL", "prefix": "figma", "description": "Figma design files"},
        "tailscale": {"env_var": "TAILSCALE_MCP_URL", "prefix": "tailscale", "description": "Tailscale network management"},
        "openai": {"env_var": "OPENAI_MCP_URL", "prefix": "openai", "description": "OpenAI and Hive Mind"},
        "vercel": {"env_var": "VERCEL_MCP_URL", "prefix": "vercel", "description": "Vercel deployments"},

        # SNOWFLAKE - NEW REDUNDANT CONFIGURATION
        "snowflake": {
            "env_var": "SNOWFLAKE_MCP_URL",
            "backup_env_var": "SNOWFLAKE_MCP_URL_BACKUP",
            "prefix": "snowflake",
            "description": "Sovereign Mind Snowflake database (Redundant East)"
        },
    }

    # Load each backend if URL is configured
    for name, config in backend_configs.items():
        url = os.environ.get(config["env_var"])
        if url:
            backends[name] = {
                "url": url,
                "prefix": config["prefix"],
                "description": config["description"],
                "enabled": True,
                "transport": config.get("transport", "json")
            }

            # Add backup URL if configured (for Snowflake redundancy)
            if "backup_env_var" in config:
                backup_url = os.environ.get(config["backup_env_var"])
                if backup_url:
                    backends[name]["backup_url"] = backup_url

            logger.info(f"Loaded backend: {name} -> {url}")

    return backends

BACKEND_MCPS = load_backends_from_env()

# =============================================================================
# TOOL CATALOG CACHE
# =============================================================================

class ToolCatalog:
    def __init__(self):
        self.tools = {}
        self.last_refresh = None
        self.refresh_interval = 300

    def needs_refresh(self):
        if self.last_refresh is None:
            return True
        return (datetime.now() - self.last_refresh).seconds > self.refresh_interval

    async def refresh(self):
        logger.info("Refreshing tool catalog from backend MCPs...")
        new_tools = {}

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            for backend_name, config in BACKEND_MCPS.items():
                if not config.get("enabled", False):
                    continue

                try:
                    headers = {"Content-Type": "application/json"}

                    # Try primary URL
                    url = config["url"]
                    response = await client.post(
                        url,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                        headers=headers
                    )

                    # If primary fails and backup exists, try backup
                    if response.status_code != 200 and "backup_url" in config:
                        logger.warning(f"  Primary {backend_name} failed, trying backup...")
                        url = config["backup_url"]
                        response = await client.post(
                            url,
                            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                            headers=headers
                        )

                    if response.status_code == 200:
                        data = response.json()
                        tools = data.get("result", {}).get("tools", [])
                        prefix = config["prefix"]

                        for tool in tools:
                            original_name = tool["name"]
                            prefixed_name = f"{prefix}_{original_name}"
                            new_tools[prefixed_name] = {
                                "backend": backend_name,
                                "backend_url": url,
                                "original_name": original_name,
                                "transport": config.get("transport", "json"),
                                "schema": {
                                    "name": prefixed_name,
                                    "description": f"[{prefix.upper()}] {tool.get('description', '')}",
                                    "inputSchema": tool.get("inputSchema", {})
                                }
                            }

                        logger.info(f"  OK {backend_name}: {len(tools)} tools loaded")
                    else:
                        logger.warning(f"  FAIL {backend_name}: HTTP {response.status_code}")

                except Exception as e:
                    logger.error(f"  ERROR {backend_name}: {e}")

        self.tools = new_tools
        self.last_refresh = datetime.now()
        logger.info(f"Tool catalog refreshed: {len(new_tools)} tools from {len([b for b in BACKEND_MCPS.values() if b.get('enabled')])}/{len(BACKEND_MCPS)} backends")

    def get_all_tools(self):
        return [tool_info["schema"] for tool_info in self.tools.values()]

    def get_tool_backend(self, tool_name):
        return self.tools.get(tool_name)

tool_catalog = ToolCatalog()

# =============================================================================
# MCP PROTOCOL HANDLERS
# =============================================================================

async def call_backend_tool(backend_name, backend_url, original_tool_name, arguments):
    """Call a tool on a backend MCP server"""
    async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
        try:
            response = await client.post(
                backend_url,
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": original_tool_name,
                        "arguments": arguments
                    }
                },
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                return response.json().get("result", {})
            else:
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({"error": f"Backend returned {response.status_code}"})
                    }]
                }
        except Exception as e:
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": str(e)})
                }]
            }

@app.route('/mcp', methods=['POST', 'OPTIONS'])
def mcp_handler():
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json(force=True)
    except:
        return jsonify({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": None
        })

    method = data.get('method')
    params = data.get('params', {})
    req_id = data.get('id')

    # Handle MCP protocol methods
    if method == 'initialize':
        # Refresh tool catalog on initialization
        if tool_catalog.needs_refresh():
            asyncio.run(tool_catalog.refresh())

        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "sovereign-mind-gateway-v3",
                "version": "3.0.1-snowflake"
            },
            "capabilities": {"tools": {}}
        }

    elif method == 'notifications/initialized':
        return '', 204

    elif method == 'tools/list':
        # Refresh if needed
        if tool_catalog.needs_refresh():
            asyncio.run(tool_catalog.refresh())

        result = {"tools": tool_catalog.get_all_tools()}

    elif method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})

        tool_info = tool_catalog.get_tool_backend(tool_name)
        if not tool_info:
            result = {
                "content": [{
                    "type": "text",
                    "text": json.dumps({"error": f"Unknown tool: {tool_name}"})
                }]
            }
        else:
            result = asyncio.run(call_backend_tool(
                tool_info["backend"],
                tool_info["backend_url"],
                tool_info["original_name"],
                arguments
            ))

    else:
        return jsonify({
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Method not found: {method}"},
            "id": req_id
        })

    return jsonify({
        "jsonrpc": "2.0",
        "result": result,
        "id": req_id
    })

@app.route('/health')
def health():
    backend_count = len([b for b in BACKEND_MCPS.values() if b.get('enabled')])
    return jsonify({
        "status": "healthy",
        "version": "3.0.1-snowflake",
        "backends": {name: {"url": cfg["url"], "enabled": cfg.get("enabled", False)} for name, cfg in BACKEND_MCPS.items()},
        "total_backends": backend_count,
        "total_tools": len(tool_catalog.tools),
        "last_refresh": tool_catalog.last_refresh.isoformat() if tool_catalog.last_refresh else None
    })

@app.route('/')
def root():
    return jsonify({
        "service": "Sovereign Mind MCP Gateway v3",
        "version": "3.0.1-snowflake",
        "endpoint": "/mcp",
        "health_endpoint": "/health",
        "backends": list(BACKEND_MCPS.keys())
    })

if __name__ == '__main__':
    # Initial tool catalog load
    asyncio.run(tool_catalog.refresh())
    logger.info(f"Gateway v3.0.1 started with {len(BACKEND_MCPS)} backends")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
