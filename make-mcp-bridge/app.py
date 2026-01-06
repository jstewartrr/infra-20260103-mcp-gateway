"""
Make.com SSE-to-HTTP Bridge MCP v2
Properly handles Make.com's bidirectional SSE-based MCP protocol
"""
import os
import json
import uuid
import requests
import threading
import queue
import time
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/mcp": {"origins": "*", "methods": ["POST", "OPTIONS"], "allow_headers": ["Content-Type", "Mcp-Session-Id"]}})

MAKE_SSE_URL = os.environ.get("MAKE_SSE_URL", "https://us2.make.com/mcp/u/7129f411-923e-4acd-b63f-d436d38939dc/sse")
TOOLS_CACHE = []
TOOLS_LOCK = threading.Lock()

class MakeSession:
    """Manages a session with Make.com SSE MCP"""
    def __init__(self, sse_url):
        self.sse_url = sse_url
        self.messages_endpoint = None
        self.response_queue = queue.Queue()
        self.sse_thread = None
        self.running = False
        
    def connect(self, timeout=30):
        """Connect to SSE and start listening"""
        try:
            response = requests.get(self.sse_url, stream=True, timeout=timeout, 
                                   headers={"Accept": "text/event-stream"})
            self.running = True
            
            for line in response.iter_lines(decode_unicode=True):
                if not self.running:
                    break
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data = line.split(":", 1)[1].strip()
                    if event_type == "endpoint":
                        base = self.sse_url.split('/mcp/')[0]
                        self.messages_endpoint = f"{base}{data}"
                        return True
                    elif event_type == "message":
                        try:
                            self.response_queue.put(json.loads(data))
                        except:
                            pass
            return False
        except Exception as e:
            print(f"SSE connect error: {e}")
            return False
    
    def send_and_receive(self, method, params=None, req_id=1, timeout=60):
        """Send request and wait for response via SSE or HTTP"""
        if not self.messages_endpoint:
            if not self.connect():
                return {"error": "Failed to connect to Make.com"}
        
        payload = {"jsonrpc": "2.0", "method": method, "id": req_id}
        if params:
            payload["params"] = params
        
        try:
            # Start SSE listener in background for responses
            response = requests.post(
                self.messages_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )
            
            # Check if response came directly
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data:
                        return data
                except:
                    pass
            
            # For 202 Accepted, need to wait for SSE response
            if response.status_code == 202:
                # Poll for response
                start = time.time()
                while time.time() - start < timeout:
                    try:
                        msg = self.response_queue.get(timeout=1)
                        if msg.get("id") == req_id:
                            return msg
                    except queue.Empty:
                        continue
                        
            return {"error": {"code": response.status_code, "message": response.text[:200]}}
            
        except Exception as e:
            return {"error": {"code": -32000, "message": str(e)}}
    
    def close(self):
        self.running = False

def make_session():
    """Create a new Make.com session"""
    session = MakeSession(MAKE_SSE_URL)
    return session

def discover_tools():
    """Discover tools from Make.com"""
    global TOOLS_CACHE
    
    session = make_session()
    
    # Initialize
    init_resp = session.send_and_receive("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "make-bridge", "version": "2.0"}
    }, 1)
    
    if "error" in init_resp:
        print(f"Initialize error: {init_resp}")
        session.close()
        return []
    
    # Send initialized notification
    session.send_and_receive("notifications/initialized", {}, 2)
    
    # List tools
    tools_resp = session.send_and_receive("tools/list", {}, 3)
    session.close()
    
    if "result" in tools_resp and "tools" in tools_resp.get("result", {}):
        with TOOLS_LOCK:
            TOOLS_CACHE = tools_resp["result"]["tools"]
        print(f"Discovered {len(TOOLS_CACHE)} Make.com tools")
        return TOOLS_CACHE
    
    print(f"Tools response: {tools_resp}")
    return []

def call_tool(tool_name, arguments):
    """Call a Make.com tool"""
    session = make_session()
    
    # Initialize session
    init_resp = session.send_and_receive("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "make-bridge", "version": "2.0"}
    }, 1)
    
    if "error" in init_resp:
        session.close()
        return {"error": f"Initialize failed: {init_resp}"}
    
    session.send_and_receive("notifications/initialized", {}, 2)
    
    # Call tool
    result = session.send_and_receive("tools/call", {
        "name": tool_name,
        "arguments": arguments or {}
    }, 3, timeout=120)
    
    session.close()
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
                "serverInfo": {"name": "make-mcp-bridge", "version": "2.0"},
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
    return jsonify({"status": "ok", "service": "make-mcp-bridge", "version": "2.0", "tools_cached": len(TOOLS_CACHE), "make_url": MAKE_SSE_URL})

@app.route('/')
def root():
    return jsonify({"service": "Make.com SSE-to-HTTP Bridge", "version": "2.0", "endpoint": "/mcp", "make_sse_url": MAKE_SSE_URL, "tools_cached": len(TOOLS_CACHE)})

@app.route('/refresh', methods=['POST'])
def refresh():
    tools = discover_tools()
    return jsonify({"success": True, "tools_discovered": len(tools)})

@app.route('/test', methods=['GET'])
def test():
    """Test Make.com connection"""
    session = make_session()
    connected = session.connect(timeout=10)
    endpoint = session.messages_endpoint
    session.close()
    return jsonify({"connected": connected, "messages_endpoint": endpoint})

if __name__ == '__main__':
    print(f"Make.com Bridge v2 starting - SSE URL: {MAKE_SSE_URL}")
    discover_tools()
    print(f"Ready with {len(TOOLS_CACHE)} tools")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
