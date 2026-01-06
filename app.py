"""
Sovereign Mind MCP Gateway v3.0.0
=================================
Complete rebuild with cv-sm-* infrastructure naming convention.
All backends on new standardized containers dated 20260105.

Author: ABBI (Adaptive Second Brain Intelligence)
"""

import os
import json
import asyncio
import httpx
import uuid
import queue
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=True)

# ============================================================================
# NEW INFRASTRUCTURE - All cv-sm-* naming convention (20260105)
# ============================================================================
BACKEND_MCPS = {
    "m365": {
        "url": os.environ.get("MCP_M365_URL", "https://cv-sm-m365-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "m365",
        "description": "Microsoft 365 email, calendar, users",
        "enabled": True,
        "transport": "json",
        "priority": 1
    },
    "asana": {
        "url": os.environ.get("MCP_ASANA_URL", "https://cv-sm-asana-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "asana",
        "description": "Asana project management",
        "enabled": True,
        "transport": "json",
        "priority": 1
    },
    "github": {
        "url": os.environ.get("MCP_GITHUB_URL", "https://cv-sm-github-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "github",
        "description": "GitHub repositories",
        "enabled": True,
        "transport": "json",
        "priority": 1
    },
    "dealcloud": {
        "url": os.environ.get("MCP_DEALCLOUD_URL", "https://cv-sm-dealcloud-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "dealcloud",
        "description": "DealCloud CRM",
        "enabled": True,
        "transport": "json",
        "priority": 1
    },
    "dropbox": {
        "url": os.environ.get("MCP_DROPBOX_URL", "https://cv-sm-dropbox-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "dropbox",
        "description": "Dropbox file storage",
        "enabled": True,
        "transport": "json",
        "priority": 1
    },
    "make": {
        "url": os.environ.get("MCP_MAKE_URL", "https://us2.make.com/mcp/u/7129f411-923e-4acd-b63f-d436d38939dc/stateless"),
        "prefix": "make",
        "description": "Make.com automation scenarios",
        "enabled": True,
        "transport": "sse",
        "priority": 2,
        "timeout": 120,
        "headers": {"Accept": "application/json, text/event-stream"}
    },
    "elevenlabs": {
        "url": os.environ.get("MCP_ELEVENLABS_URL", "https://cv-sm-elevenlabs-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "elevenlabs",
        "description": "ElevenLabs voice agents (ABBI)",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "simli": {
        "url": os.environ.get("MCP_SIMLI_URL", "https://cv-sm-simli-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "simli",
        "description": "Simli visual avatars",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "gemini": {
        "url": os.environ.get("MCP_GEMINI_URL", "https://cv-sm-gemini-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "gemini",
        "description": "Google Gemini AI",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "figma": {
        "url": os.environ.get("MCP_FIGMA_URL", "https://cv-sm-figma-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "figma",
        "description": "Figma design files",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "tailscale": {
        "url": os.environ.get("MCP_TAILSCALE_URL", "https://cv-sm-tailscale-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "tailscale",
        "description": "Tailscale network management",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "openai": {
        "url": os.environ.get("MCP_OPENAI_URL", "https://cv-sm-openai-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "openai",
        "description": "OpenAI GPT models and Hive Mind",
        "enabled": True,
        "transport": "json",
        "priority": 2
    },
    "vercel": {
        "url": os.environ.get("MCP_VERCEL_URL", "https://cv-sm-vercel-20260105.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp"),
        "prefix": "vercel",
        "description": "Vercel deployments, projects, domains",
        "enabled": True,
        "transport": "json",
        "priority": 2
    }
}

def parse_sse_response(text: str) -> Optional[Dict]:
    for line in text.split('\n'):
        if line.startswith('data: '):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    return None

class ToolCatalog:
    def __init__(self):
        self.tools: Dict[str, Dict] = {}
        self.backend_health: Dict[str, Dict] = {}
        self.last_refresh: Optional[datetime] = None
        self.refresh_interval = 300
    
    def needs_refresh(self) -> bool:
        if self.last_refresh is None:
            return True
        return (datetime.now() - self.last_refresh).seconds > self.refresh_interval
    
    async def refresh(self):
        logger.info("Refreshing tool catalog from backend MCPs...")
        new_tools = {}
        health_status = {}
        sorted_backends = sorted(
            [(k, v) for k, v in BACKEND_MCPS.items() if v.get("enabled", False)],
            key=lambda x: x[1].get("priority", 99)
        )
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            for backend_name, config in sorted_backends:
                health_status[backend_name] = {"status": "unknown", "tools": 0, "error": None}
                try:
                    headers = {"Content-Type": "application/json"}
                    if config.get("headers"):
                        headers.update(config["headers"])
                    timeout = config.get("timeout", 30.0)
                    url = config["url"]
                    response = await client.post(
                        url,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                        headers=headers,
                        timeout=timeout
                    )
                    if response.status_code == 200:
                        if config.get("transport") == "sse":
                            data = parse_sse_response(response.text)
                        else:
                            data = response.json()
                        if not data:
                            health_status[backend_name] = {"status": "error", "tools": 0, "error": "Could not parse response"}
                            continue
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
                                "headers": config.get("headers", {}),
                                "timeout": config.get("timeout", 60.0),
                                "schema": {
                                    "name": prefixed_name,
                                    "description": f"[{prefix.upper()}] {tool.get('description', '')}",
                                    "inputSchema": tool.get("inputSchema", {})
                                }
                            }
                        health_status[backend_name] = {"status": "healthy", "tools": len(tools), "error": None}
                        logger.info(f"  OK {backend_name}: {len(tools)} tools loaded")
                    else:
                        health_status[backend_name] = {"status": "error", "tools": 0, "error": f"HTTP {response.status_code}"}
                except httpx.TimeoutException:
                    health_status[backend_name] = {"status": "timeout", "tools": 0, "error": "Connection timeout"}
                except Exception as e:
                    health_status[backend_name] = {"status": "error", "tools": 0, "error": str(e)[:100]}
        self.tools = new_tools
        self.backend_health = health_status
        self.last_refresh = datetime.now()
        healthy_count = sum(1 for h in health_status.values() if h["status"] == "healthy")
        logger.info(f"Tool catalog refreshed: {len(self.tools)} tools from {healthy_count}/{len(sorted_backends)} backends")
    
    def get_all_tools(self):
        return [t["schema"] for t in self.tools.values()]
    
    def get_tool(self, prefixed_name: str) -> Optional[Dict]:
        return self.tools.get(prefixed_name)
    
    def get_health_report(self) -> Dict:
        return {
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None,
            "total_tools": len(self.tools),
            "backends": self.backend_health
        }

catalog = ToolCatalog()
sse_sessions: Dict[str, queue.Queue] = {}

NATIVE_TOOLS = [
    {
        "name": "hivemind_write",
        "description": "[GATEWAY] Write to Sovereign Mind Hive Mind shared memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source identifier"},
                "category": {"type": "string", "description": "Category: CONTEXT, DECISION, ACTION_ITEM, etc"},
                "workstream": {"type": "string", "description": "Workstream or project name", "default": "GENERAL"},
                "summary": {"type": "string", "description": "Clear summary", "maxLength": 2000},
                "details": {"type": "object", "description": "JSON details object"},
                "priority": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"], "default": "MEDIUM"},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["source", "category", "summary"]
        }
    },
    {
        "name": "hivemind_read",
        "description": "[GATEWAY] Read from Sovereign Mind Hive Mind",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "maximum": 50},
                "category": {"type": "string"},
                "source": {"type": "string"},
                "workstream": {"type": "string"}
            }
        }
    },
    {
        "name": "gateway_status",
        "description": "[GATEWAY] Get status of all MCP backends",
        "inputSchema": {"type": "object", "properties": {}}
    }
]

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def call_backend_tool(backend_url: str, tool_name: str, arguments: dict, transport: str = "json", extra_headers: dict = None, timeout: float = 60.0):
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        response = await client.post(
            backend_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
            headers=headers
        )
        if transport == "sse":
            return parse_sse_response(response.text)
        return response.json()

def handle_native_tool(tool_name: str, arguments: dict) -> Dict:
    if tool_name == "gateway_status":
        return {"content": [{"type": "text", "text": json.dumps({"gateway": "sovereign_mind_gateway", "version": "3.0.0", "infrastructure": "cv-sm-*-20260105", "timestamp": datetime.now().isoformat(), "health": catalog.get_health_report(), "backends_configured": list(BACKEND_MCPS.keys())}, indent=2)}]}
    elif tool_name == "hivemind_write":
        return {"content": [{"type": "text", "text": "Error: Use Snowflake MCP directly (Slot 3)"}], "isError": True}
    elif tool_name == "hivemind_read":
        return {"content": [{"type": "text", "text": "Error: Use Snowflake MCP directly (Slot 3)"}], "isError": True}
    return {"content": [{"type": "text", "text": f"Unknown native tool: {tool_name}"}], "isError": True}

def handle_initialize(params: dict) -> Dict:
    return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "sovereign-mind-gateway", "version": "3.0.0"}}

def handle_tools_list(params: dict) -> Dict:
    if catalog.needs_refresh():
        run_async(catalog.refresh())
    return {"tools": catalog.get_all_tools() + NATIVE_TOOLS}

def handle_tools_call(params: dict) -> Dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    native_names = [t["name"] for t in NATIVE_TOOLS]
    if tool_name in native_names:
        return handle_native_tool(tool_name, arguments)
    tool_info = catalog.get_tool(tool_name)
    if not tool_info:
        return {"content": [{"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}], "isError": True}
    try:
        result = run_async(call_backend_tool(tool_info["backend_url"], tool_info["original_name"], arguments, tool_info.get("transport", "json"), tool_info.get("headers", {}), tool_info.get("timeout", 60.0)))
        if result and "result" in result:
            return result["result"]
        elif result and "error" in result:
            return {"content": [{"type": "text", "text": f"Backend error: {result['error']}"}], "isError": True}
        else:
            return result if result else {"content": [{"type": "text", "text": "No response from backend"}], "isError": True}
    except Exception as e:
        logger.error(f"Error calling backend tool {tool_name}: {e}")
        return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

def process_mcp_message(data: dict) -> Dict:
    method = data.get("method", "")
    params = data.get("params", {})
    request_id = data.get("id", 1)
    logger.info(f"MCP request: {method}")
    handlers = {"initialize": handle_initialize, "tools/list": handle_tools_list, "tools/call": handle_tools_call, "notifications/initialized": lambda p: {}}
    handler = handlers.get(method)
    if handler:
        result = handler(params)
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "sovereign-mind-gateway", "version": "3.0.0", "infrastructure": "cv-sm-*-20260105", "backends": list(BACKEND_MCPS.keys()), "total_tools": len(catalog.tools) + len(NATIVE_TOOLS) if catalog.tools else "not yet loaded"})

@app.route("/mcp", methods=["POST"])
def mcp_handler():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), 400
        response = process_mcp_message(data)
        return jsonify(response)
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        return jsonify({"jsonrpc": "2.0", "id": data.get("id", 1) if data else 1, "error": {"code": -32603, "message": str(e)}}), 500

@app.route("/sse", methods=["GET"])
def sse_connect():
    session_id = str(uuid.uuid4())
    sse_sessions[session_id] = queue.Queue()
    def generate():
        yield f"event: endpoint\ndata: /sse/{session_id}/message\n\n"
        while True:
            try:
                message = sse_sessions[session_id].get(timeout=30)
                yield f"event: message\ndata: {json.dumps(message)}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
            except GeneratorExit:
                break
            except Exception:
                break
        if session_id in sse_sessions:
            del sse_sessions[session_id]
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.route("/sse/<session_id>/message", methods=["POST"])
def sse_message(session_id):
    if session_id not in sse_sessions:
        return jsonify({"error": "Session not found"}), 404
    try:
        data = request.get_json()
        response = process_mcp_message(data)
        sse_sessions[session_id].put(response)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/refresh", methods=["POST"])
def force_refresh():
    run_async(catalog.refresh())
    return jsonify({"status": "refreshed", "total_tools": len(catalog.tools) + len(NATIVE_TOOLS), "health": catalog.get_health_report()})

@app.route("/tools", methods=["GET"])
def list_tools():
    if catalog.needs_refresh():
        run_async(catalog.refresh())
    tools_by_backend = {"_native": [{"name": t["name"], "description": t.get("description", "")} for t in NATIVE_TOOLS]}
    for name, info in catalog.tools.items():
        backend = info["backend"]
        if backend not in tools_by_backend:
            tools_by_backend[backend] = []
        tools_by_backend[backend].append({"prefixed_name": name, "original_name": info["original_name"]})
    return jsonify({"total_tools": len(catalog.tools) + len(NATIVE_TOOLS), "backends": tools_by_backend, "health": catalog.get_health_report()})

@app.route("/health", methods=["GET"])
def detailed_health():
    return jsonify(catalog.get_health_report())

if __name__ == "__main__":
    logger.info("Sovereign Mind MCP Gateway v3.0.0 starting...")
    run_async(catalog.refresh())
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
