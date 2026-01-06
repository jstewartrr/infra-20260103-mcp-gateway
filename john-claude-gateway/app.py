"""
John Claude Unified MCP Gateway v4.1 - With RAG Semantic Search + Vercel MCP
"""
import os, json, uuid, requests
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import snowflake.connector

app = Flask(__name__)
CORS(app, resources={r"/mcp": {"origins": "*", "methods": ["POST", "OPTIONS"], "allow_headers": ["Content-Type", "Mcp-Session-Id"]}})

SERVICES = {
    "snowflake": {"url": None, "type": "internal"},
    "google_drive": {"url": "https://google-drive-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "elevenlabs": {"url": "https://elevenlabs-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "simli": {"url": "https://simli-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "notebooklm": {"url": "https://notebooklm-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "vertex_ai": {"url": "https://vertex-ai-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "figma": {"url": "https://figma-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "vectorizer": {"url": "https://slide-transform-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "github": {"url": "https://github-mcp.redglacier-26075659.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "azure_cli": {"url": "https://azure-cli-mcp.calmsmoke-f302257e.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "gemini": {"url": "https://gemini-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "asana": {"url": "https://mcp.asana.com/sse", "type": "sse"},
    "vercel": {"url": "https://vercel-mcp.lemoncoast-87756bcf.eastus.azurecontainerapps.io/mcp", "type": "http"},
    "make": {"url": "https://mcp.make.com", "type": "sse"},
}

ALL_TOOLS, TOOL_REGISTRY = [], {}
GATEWAY_TOOLS = [
    {"name": "hive_mind_query", "description": "Query Sovereign Mind Hive Mind shared memory", "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["sql"]}},
    {"name": "hive_mind_write", "description": "Write to Hive Mind shared memory", "inputSchema": {"type": "object", "properties": {"category": {"type": "string"}, "summary": {"type": "string"}}, "required": ["category", "summary"]}},
    {"name": "rag_search", "description": "Semantic search across all Sovereign Mind knowledge - returns most relevant context for any query", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Natural language query to find relevant context"}, "limit": {"type": "integer", "default": 5}}, "required": ["query"]}},
    {"name": "list_services", "description": "List all available MCP services and their status", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "refresh_tools", "description": "Re-discover tools from all backend services", "inputSchema": {"type": "object", "properties": {}}}
]

def get_sf(): 
    return snowflake.connector.connect(
        user=os.environ.get('SNOWFLAKE_USER','JOHN_CLAUDE'), 
        password=os.environ.get('SNOWFLAKE_PASSWORD'), 
        account=os.environ.get('SNOWFLAKE_ACCOUNT'), 
        warehouse='SOVEREIGN_MIND_WH', 
        database='SOVEREIGN_MIND', 
        schema='RAW'
    )

def exec_gw(n, a):
    global ALL_TOOLS
    if n == "hive_mind_query":
        try:
            c = get_sf(); cur = c.cursor(); sql = a.get('sql','')
            if 'LIMIT' not in sql.upper(): sql += f" LIMIT {a.get('limit',10)}"
            cur.execute(sql); r = [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]; cur.close(); c.close()
            return {"success": True, "data": r}
        except Exception as e: return {"error": str(e)}
    
    elif n == "hive_mind_write":
        try:
            c = get_sf(); cur = c.cursor()
            cur.execute(f"INSERT INTO SHARED_MEMORY (SOURCE,CATEGORY,SUMMARY,STATUS) VALUES ('GATEWAY','{a.get('category','')}','{a.get('summary','').replace(chr(39),chr(39)+chr(39))}','ACTIVE')")
            c.commit(); cur.close(); c.close(); return {"success": True}
        except Exception as e: return {"error": str(e)}
    
    elif n == "rag_search":
        try:
            c = get_sf(); cur = c.cursor()
            query = a.get('query', '').replace("'", "''")
            limit = a.get('limit', 5)
            sql = f"""
            SELECT 
                SOURCE_TABLE,
                CONTENT,
                ROUND(VECTOR_COSINE_SIMILARITY(EMBEDDING, SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', '{query}')), 3) as SIMILARITY
            FROM SOVEREIGN_MIND.RAW.MEMORY_EMBEDDINGS
            ORDER BY SIMILARITY DESC
            LIMIT {limit}
            """
            cur.execute(sql)
            results = [{"source": row[0], "content": row[1], "relevance": row[2]} for row in cur.fetchall()]
            cur.close(); c.close()
            return {"success": True, "results": results, "query": a.get('query')}
        except Exception as e: return {"error": str(e)}
    
    elif n == "list_services": 
        return {"services": list(SERVICES.keys()), "tools": len(ALL_TOOLS), "gateway_tools": len(GATEWAY_TOOLS)}
    
    elif n == "refresh_tools":
        ALL_TOOLS = [t for sn,cfg in SERVICES.items() for t in discover(sn,cfg)]
        return {"success": True, "tools_discovered": len(ALL_TOOLS)}
    
    return {"error": "Unknown gateway tool"}

def discover(sn, cfg):
    if cfg["type"] == "internal": return []
    if cfg["type"] == "sse": return discover_sse(sn, cfg)
    try:
        r = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}},"id":1}, timeout=15)
        if r.status_code == 200:
            tr = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}, timeout=15)
            if tr.status_code == 200:
                tools = []
                for t in tr.json().get("result",{}).get("tools",[]):
                    orig = t["name"]; t["name"] = f"{sn}_{orig}"; t["description"] = f"[{sn.upper()}] {t.get('description','')}"
                    TOOL_REGISTRY[t["name"]] = {"s": sn, "o": orig}; tools.append(t)
                return tools
    except Exception as e: print(f"Discovery failed for {sn}: {e}")
    return []

def discover_sse(sn, cfg):
    try:
        r = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}},"id":1}, timeout=15, headers={"Accept": "application/json"})
        if r.status_code == 200:
            tr = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}, timeout=15)
            if tr.status_code == 200:
                tools = []
                for t in tr.json().get("result",{}).get("tools",[]):
                    orig = t["name"]; t["name"] = f"{sn}_{orig}"; t["description"] = f"[{sn.upper()}] {t.get('description','')}"
                    TOOL_REGISTRY[t["name"]] = {"s": sn, "o": orig}; tools.append(t)
                return tools
    except Exception as e: print(f"SSE discovery failed for {sn}: {e}")
    return []

def proxy(sn, orig, args):
    cfg = SERVICES.get(sn)
    if not cfg: return {"error": f"Unknown service: {sn}"}
    try:
        r = requests.post(cfg["url"], json={"jsonrpc":"2.0","method":"tools/call","params":{"name":orig,"arguments":args},"id":3}, timeout=120)
        return r.json().get("result",{}) if r.status_code == 200 else {"error": str(r.status_code)}
    except Exception as e: return {"error": str(e)}

@app.route('/mcp', methods=['POST','OPTIONS'])
def mcp():
    global ALL_TOOLS
    if request.method == 'OPTIONS': return '', 204
    try: d = request.get_json(force=True)
    except: return jsonify({"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":None})
    m, p, rid = d.get('method'), d.get('params',{}), d.get('id')
    sid = request.headers.get('Mcp-Session-Id') or str(uuid.uuid4())
    try:
        if m == 'initialize':
            if not ALL_TOOLS: ALL_TOOLS = [t for sn,cfg in SERVICES.items() for t in discover(sn,cfg)]
            result = {"protocolVersion":"2024-11-05","serverInfo":{"name":"john-claude-gateway","version":"4.1-vercel"},"capabilities":{"tools":{}}}
        elif m == 'notifications/initialized': return '', 204
        elif m == 'tools/list': result = {"tools": GATEWAY_TOOLS + ALL_TOOLS}
        elif m == 'tools/call':
            tn, ta = p.get('name'), p.get('arguments',{})
            if tn in [t["name"] for t in GATEWAY_TOOLS]: tr = exec_gw(tn, ta)
            elif tn in TOOL_REGISTRY: tr = proxy(TOOL_REGISTRY[tn]["s"], TOOL_REGISTRY[tn]["o"], ta)
            else: tr = {"error": f"Unknown tool: {tn}"}
            result = {"content":[{"type":"text","text":json.dumps(tr,default=str)}]}
        else: return jsonify({"jsonrpc":"2.0","error":{"code":-32601,"message":m},"id":rid})
        r = make_response(jsonify({"jsonrpc":"2.0","result":result,"id":rid}))
        r.headers['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'; r.headers['Mcp-Session-Id'] = sid
        return r
    except Exception as e: return jsonify({"jsonrpc":"2.0","error":{"code":-32000,"message":str(e)},"id":rid})

@app.route('/health')
def health(): return jsonify({"status":"ok","version":"4.1-vercel","services":len(SERVICES),"tools":len(ALL_TOOLS),"rag_enabled":True})

@app.route('/')
def root(): return jsonify({"service":"John Claude Unified Gateway","version":"4.1-vercel","endpoint":"/mcp","services":list(SERVICES.keys()),"features":["rag_search","hive_mind","vercel"]})

if __name__ == '__main__':
    ALL_TOOLS = [t for sn,cfg in SERVICES.items() for t in discover(sn,cfg)]
    print(f"Gateway v4.1 (Vercel) started with {len(SERVICES)} services and {len(ALL_TOOLS)} tools")
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8080)))
