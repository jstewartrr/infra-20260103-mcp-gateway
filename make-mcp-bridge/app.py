"""
Make.com SSE-to-HTTP Bridge MCP
Converts Make.com's SSE transport to standard HTTP JSON-RPC for gateway integration
"""
import os
import json
import uuid
import requests
import sseclient
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from threading import Lock

app = Flask(__name__)
CORS(app, resources={r"/mcp": {"origins": "*", "methods": ["POST", "OPTIONS"], "allow_headers": ["Content-Type", "Mcp-Session-Id"]}})

MAKE_SSE_URL = os.environ.get("MAKE_SSE_URL", "https://us2.make.com/mcp/u/7129f411-923e-4acd-b63f-d436d38939dc/sse")
MAKE_BASE_URL = MAKE_SSE_URL.rsplit('/sse', 1)[0]

TOOLS_CACHE = []
TOOLS_LOCK = Lock()

def get_sse_endpoint():
    """Connect to SSE and get the messages endpoint"""
    try:
        response = requests.get(MAKE_SSE_URL, stream=True, timeout=30, headers={"Accept": "text/event-stream"})
        client = sseclient.SSEClient(response)
        
        for event in client.events():
            if event.event == "endpoint":
                endpoint_path = event.data
                base = MAKE_SSE_URL.split('/mcp/')[0]
                full_url = f"{base}{endpoint_path}"
                return full_url
            break
    except Exception as e:
        print(f"SSE endpoint error: {e}")
    return None

def send_jsonrpc(endpoint, method, params=None, req_id=1):
    """Send JSON-RPC request to Make.com messages endpoint"""
    payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
    if params:
        payload["params"] = params
    
    try:
        response = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 202:
            return {"result": {"status": "accepted"}}
        else:
            return {"error": {"code": response.status_code, "message": response.text}}
    except Exception as e:
        return {"error": {"code": -32000, "message": str(e)}}

def discover_tools():
    """Discover tools from Make.com"""
    global TOOLS_CACHE
    
    endpoint = get_sse_endpoint()
    if not endpoint:
        print("Failed to get SSE endpoint")
        return []
    
    init_resp = send_jsonrpc(endpoint, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "make-bridge", "version": "1.0"}
    }, 1)
    
    if "error" in init_resp:
        print(f"Initialize error: {init_resp}")
        return []
    
    send_jsonrpc(endpoint, "notifications/initialized", {}, 2)
    tools_resp = send_jsonrpc(endpoint, "tools/list", {}, 3)
    
    if "result" in tools_resp and "tools" in tools_resp["result"]:
        with TOOLS_LOCK:
            TOOLS_CACHE = tools_resp["result"]["tools"]
        print(f"Discovered {len(TOOLS_CACHE)} Make.com tools")
        return TOOLS_CACHE
    
    return []

def call_tool(tool_name, arguments):
    """Call a Make.com tool"""
    endpoint = get_sse_endpoint()
    if not endpoint:
        return {"error": "Failed to connect to Make.com SSE"}
    
    init_resp = send_jsonrpc(endpoint, "initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "make-bridge", "version": "1.0"}
    }, 1)
    
    if "error" in init_resp:
        return {"error": f"Initialize failed: {init_resp}"}
    
    send_jsonrpc(endpoint, "notifications/initialized", {}, 2)
    
    result = send_jsonrpc(endpoint, "tools/call", {
        "name": tool_name,
        "arguments": arguments or {}
    }, 3)
    
    return result.get("result", result)

@app.route('/mcp', methods=['POST', 'OPTIONS'])
def mcp():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        d = request.get_json(force=True)
    except:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    
    method = d.get('method')
    params = d.get('params', {})
    rid = d.get('id')
    sid = request.headers.get('Mcp-Session-Id') or str(uuid.uuid4())
    
    try:
        if method == 'initialize':
            if not TOOLS_CACHE:
                discover_tools()
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "make-mcp-bridge", "version": "1.0"},
                "capabilities": {"tools": {}}
            }
        
        elif method == 'notifications/initialized':
            return '', 204
        
        elif method == 'tools/list':
            if not TOOLS_CACHE:
                discover_tools()
            result = {"tools": TOOLS_CACHE}
        
        elif method == 'tools/call':
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            tool_result = call_tool(tool_name, arguments)
            
            if isinstance(tool_result, dict) and "content" in tool_result:
                result = tool_result
            else:
                result = {"content": [{"type": "text", "text": json.dumps(tool_result, default=str)}]}
        
        else:
            return jsonify({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown method: {method}"}, "id": rid})
        
        response = make_response(jsonify({"jsonrpc": "2.0", "result": result, "id": rid}))
        response.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'
        response.headers['Mcp-Session-Id'] = sid
        return response
    
    except Exception as e:
        return jsonify({"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)}, "id": rid})

@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "make-mcp-bridge", "version": "1.0", "tools_cached": len(TOOLS_CACHE), "make_url": MAKE_SSE_URL})

@app.route('/')
def root():
    return jsonify({"service": "Make.com SSE-to-HTTP Bridge", "version": "1.0", "endpoint": "/mcp", "make_sse_url": MAKE_SSE_URL, "tools_cached": len(TOOLS_CACHE)})

@app.route('/refresh', methods=['POST'])
def refresh():
    tools = discover_tools()
    return jsonify({"success": True, "tools_discovered": len(tools)})

if __name__ == '__main__':
    print(f"Make.com Bridge starting - SSE URL: {MAKE_SSE_URL}")
    discover_tools()
    print(f"Ready with {len(TOOLS_CACHE)} tools")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
