"""CV SM Dropbox MCP with Team Token Support"""
from flask import Flask, request, jsonify
import dropbox
from dropbox.exceptions import AuthError, BadInputError
import os
import json

app = Flask(__name__)

ACCESS_TOKEN = os.environ.get('DROPBOX_ACCESS_TOKEN')
SELECT_USER = os.environ.get('DROPBOX_SELECT_USER')  # Team member ID

def get_dbx():
    """Get Dropbox client with team user selection if configured"""
    headers = {}
    if SELECT_USER:
        headers['Dropbox-API-Select-User'] = SELECT_USER
    return dropbox.Dropbox(ACCESS_TOKEN, headers=headers)

TOOLS = [
    {"name": "dropbox_test_connection", "description": "Test the Dropbox API connection and return account info.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "dropbox_list_folder", "description": "List files and folders in a Dropbox directory.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Dropbox folder path (use '' for root)"}, "recursive": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 100}}}},
    {"name": "dropbox_search_files", "description": "Search for files and folders in Dropbox.", "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}, "path": {"type": "string", "description": "Limit search to this folder"}, "file_extensions": {"type": "array", "items": {"type": "string"}}, "max_results": {"type": "integer", "default": 50}}, "required": ["query"]}},
    {"name": "dropbox_download_file", "description": "Download a file from Dropbox.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Full path to the file"}, "as_text": {"type": "boolean", "default": True}}, "required": ["path"]}},
    {"name": "dropbox_read_text_file", "description": "Read the text content of a file.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Full path to the text file"}, "max_bytes": {"type": "integer", "default": 1000000}}, "required": ["path"]}},
    {"name": "dropbox_upload_file", "description": "Upload a file to Dropbox.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Destination path in Dropbox"}, "content": {"type": "string", "description": "File content"}, "is_base64": {"type": "boolean", "default": False}, "overwrite": {"type": "boolean", "default": True}}, "required": ["path", "content"]}},
    {"name": "dropbox_create_folder", "description": "Create a new folder in Dropbox.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Full path for the new folder"}}, "required": ["path"]}},
    {"name": "dropbox_delete_file", "description": "Delete a file or folder.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string", "description": "Path to delete"}}, "required": ["path"]}},
    {"name": "dropbox_move_file", "description": "Move or rename a file or folder.", "inputSchema": {"type": "object", "properties": {"from_path": {"type": "string"}, "to_path": {"type": "string"}}, "required": ["from_path", "to_path"]}},
    {"name": "dropbox_copy_file", "description": "Copy a file or folder.", "inputSchema": {"type": "object", "properties": {"from_path": {"type": "string"}, "to_path": {"type": "string"}}, "required": ["from_path", "to_path"]}},
    {"name": "dropbox_get_file_metadata", "description": "Get detailed metadata for a file or folder.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "dropbox_get_shared_link", "description": "Get or create a shared link for a file.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "create_if_missing": {"type": "boolean", "default": True}}, "required": ["path"]}},
    {"name": "dropbox_list_revisions", "description": "List previous versions of a file.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["path"]}},
    {"name": "dropbox_get_space_usage", "description": "Get Dropbox account storage usage.", "inputSchema": {"type": "object", "properties": {}}}
]

def dropbox_test_connection():
    try:
        dbx = get_dbx()
        account = dbx.users_get_current_account()
        return {"success": True, "account": {"email": account.email, "name": account.name.display_name, "account_id": account.account_id}}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_list_folder(path="", recursive=False, limit=100):
    try:
        dbx = get_dbx()
        result = dbx.files_list_folder(path, recursive=recursive, limit=limit)
        entries = []
        for entry in result.entries:
            e = {"name": entry.name, "path": entry.path_display, "type": "folder" if isinstance(entry, dropbox.files.FolderMetadata) else "file"}
            if hasattr(entry, 'size'): e["size"] = entry.size
            if hasattr(entry, 'client_modified'): e["modified"] = str(entry.client_modified)
            entries.append(e)
        return {"success": True, "entries": entries, "has_more": result.has_more}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_search_files(query, path=None, file_extensions=None, max_results=50):
    try:
        dbx = get_dbx()
        options = dropbox.files.SearchOptions(max_results=max_results, path=path) if path else dropbox.files.SearchOptions(max_results=max_results)
        result = dbx.files_search_v2(query, options=options)
        matches = []
        for match in result.matches:
            if hasattr(match, 'metadata') and hasattr(match.metadata, 'metadata'):
                m = match.metadata.metadata
                matches.append({"name": m.name, "path": m.path_display})
        return {"success": True, "matches": matches}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_download_file(path, as_text=True):
    try:
        dbx = get_dbx()
        _, response = dbx.files_download(path)
        content = response.content
        if as_text:
            return {"success": True, "content": content.decode('utf-8', errors='replace')}
        else:
            import base64
            return {"success": True, "content": base64.b64encode(content).decode('ascii'), "encoding": "base64"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_read_text_file(path, max_bytes=1000000):
    return dropbox_download_file(path, as_text=True)

def dropbox_upload_file(path, content, is_base64=False, overwrite=True):
    try:
        dbx = get_dbx()
        if is_base64:
            import base64
            data = base64.b64decode(content)
        else:
            data = content.encode('utf-8')
        mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
        result = dbx.files_upload(data, path, mode=mode)
        return {"success": True, "path": result.path_display, "size": result.size}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_create_folder(path):
    try:
        dbx = get_dbx()
        result = dbx.files_create_folder_v2(path)
        return {"success": True, "path": result.metadata.path_display}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_delete_file(path):
    try:
        dbx = get_dbx()
        dbx.files_delete_v2(path)
        return {"success": True, "deleted": path}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_move_file(from_path, to_path):
    try:
        dbx = get_dbx()
        result = dbx.files_move_v2(from_path, to_path)
        return {"success": True, "from": from_path, "to": result.metadata.path_display}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_copy_file(from_path, to_path):
    try:
        dbx = get_dbx()
        result = dbx.files_copy_v2(from_path, to_path)
        return {"success": True, "from": from_path, "to": result.metadata.path_display}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_get_file_metadata(path):
    try:
        dbx = get_dbx()
        m = dbx.files_get_metadata(path)
        result = {"name": m.name, "path": m.path_display}
        if hasattr(m, 'size'): result["size"] = m.size
        if hasattr(m, 'client_modified'): result["modified"] = str(m.client_modified)
        return {"success": True, "metadata": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_get_shared_link(path, create_if_missing=True):
    try:
        dbx = get_dbx()
        try:
            links = dbx.sharing_list_shared_links(path=path).links
            if links:
                return {"success": True, "url": links[0].url}
        except: pass
        if create_if_missing:
            link = dbx.sharing_create_shared_link_with_settings(path)
            return {"success": True, "url": link.url}
        return {"success": False, "error": "No shared link exists"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_list_revisions(path, limit=10):
    try:
        dbx = get_dbx()
        result = dbx.files_list_revisions(path, limit=limit)
        revisions = [{"rev": r.rev, "modified": str(r.server_modified), "size": r.size} for r in result.entries]
        return {"success": True, "revisions": revisions}
    except Exception as e:
        return {"success": False, "error": str(e)}

def dropbox_get_space_usage():
    try:
        dbx = get_dbx()
        usage = dbx.users_get_space_usage()
        return {"success": True, "used": usage.used, "allocated": usage.allocation.get_individual().allocated if hasattr(usage.allocation, 'get_individual') else None}
    except Exception as e:
        return {"success": False, "error": str(e)}

TOOL_HANDLERS = {
    "dropbox_test_connection": dropbox_test_connection,
    "dropbox_list_folder": dropbox_list_folder,
    "dropbox_search_files": dropbox_search_files,
    "dropbox_download_file": dropbox_download_file,
    "dropbox_read_text_file": dropbox_read_text_file,
    "dropbox_upload_file": dropbox_upload_file,
    "dropbox_create_folder": dropbox_create_folder,
    "dropbox_delete_file": dropbox_delete_file,
    "dropbox_move_file": dropbox_move_file,
    "dropbox_copy_file": dropbox_copy_file,
    "dropbox_get_file_metadata": dropbox_get_file_metadata,
    "dropbox_get_shared_link": dropbox_get_shared_link,
    "dropbox_list_revisions": dropbox_list_revisions,
    "dropbox_get_space_usage": dropbox_get_space_usage,
}

@app.route('/mcp', methods=['POST'])
def mcp_handler():
    data = request.get_json()
    method = data.get('method', '')
    params = data.get('params', {})
    req_id = data.get('id', 1)
    
    if method == 'initialize':
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "cv-sm-dropbox", "version": "2.0.0"}}})
    elif method == 'tools/list':
        return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == 'tools/call':
        tool_name = params.get('name', '')
        args = params.get('arguments', {})
        if tool_name in TOOL_HANDLERS:
            result = TOOL_HANDLERS[tool_name](**args)
            return jsonify({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}})
        return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})
    return jsonify({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "cv-sm-dropbox", "version": "2.0.0", "select_user": SELECT_USER})

@app.route('/', methods=['GET'])
def root():
    return jsonify({"service": "cv-sm-dropbox", "version": "2.0.0", "tools": len(TOOLS)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
