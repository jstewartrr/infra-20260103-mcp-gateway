"""
Microsoft 365 MCP Server - ABBI's M365 Integration
Provides email, calendar, and user management via Microsoft Graph API
"""

from flask import Flask, request, jsonify
import httpx
import os
import json
from datetime import datetime, timedelta
from functools import lru_cache
import time

app = Flask(__name__)

# Configuration
TENANT_ID = os.environ.get("TENANT_ID", "5e558f98-613b-4c55-80e7-4fd3273d8df3")
CLIENT_ID = os.environ.get("CLIENT_ID", "9969e8ef-8c3b-4ea1-bf85-9a88e1371ab4")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
DEFAULT_USER = os.environ.get("DEFAULT_USER", "John.Claude@middleground.com")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

# Token cache
_token_cache = {"token": None, "expires_at": 0}


def get_access_token():
    """Get or refresh access token"""
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    
    response = httpx.post(TOKEN_URL, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"
    })
    
    data = response.json()
    if "access_token" in data:
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
        return data["access_token"]
    else:
        raise Exception(f"Token error: {data}")


def graph_request(method, endpoint, user=None, **kwargs):
    """Make authenticated Graph API request"""
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Prepend user path if needed
    if user and not endpoint.startswith("/users/"):
        endpoint = f"/users/{user}{endpoint}"
    elif not user and not endpoint.startswith("/users/"):
        endpoint = f"/users/{DEFAULT_USER}{endpoint}"
    
    url = f"{GRAPH_BASE}{endpoint}"
    
    with httpx.Client(timeout=30) as client:
        response = client.request(method, url, headers=headers, **kwargs)
        if response.status_code == 204:
            return {"success": True}
        return response.json()


# ============ MCP PROTOCOL ============

TOOLS = [
    {
        "name": "read_emails",
        "description": "Read emails from inbox. Returns subject, from, date, and preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User mailbox (default: John.Claude@middleground.com)"},
                "folder": {"type": "string", "description": "Folder name (default: inbox)"},
                "top": {"type": "integer", "description": "Number of emails to return (default: 10)"},
                "unread_only": {"type": "boolean", "description": "Only return unread emails"},
                "search": {"type": "string", "description": "Search query"}
            }
        }
    },
    {
        "name": "get_email",
        "description": "Get full email content by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User mailbox"},
                "message_id": {"type": "string", "description": "Email message ID"}
            },
            "required": ["message_id"]
        }
    },
    {
        "name": "send_email",
        "description": "Send an email from the specified user",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "Send as this user (default: John.Claude@middleground.com)"},
                "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses"},
                "cc": {"type": "array", "items": {"type": "string"}, "description": "CC recipients"},
                "bcc": {"type": "array", "items": {"type": "string"}, "description": "BCC recipients"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body (HTML or plain text)"},
                "is_html": {"type": "boolean", "description": "Body is HTML (default: false)"},
                "importance": {"type": "string", "enum": ["low", "normal", "high"], "description": "Email importance"},
                "attachments": {
                    "type": "array",
                    "description": "File attachments",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Filename"},
                            "content_type": {"type": "string", "description": "MIME type (e.g. application/pdf)"},
                            "content_bytes": {"type": "string", "description": "Base64 encoded file content"}
                        },
                        "required": ["name", "content_bytes"]
                    }
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "reply_email",
        "description": "Reply to an email",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User mailbox"},
                "message_id": {"type": "string", "description": "Original message ID"},
                "body": {"type": "string", "description": "Reply body"},
                "reply_all": {"type": "boolean", "description": "Reply to all recipients"}
            },
            "required": ["message_id", "body"]
        }
    },
    {
        "name": "search_emails",
        "description": "Search emails across mailbox",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User mailbox"},
                "query": {"type": "string", "description": "Search query (KQL syntax)"},
                "top": {"type": "integer", "description": "Max results (default: 25)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "list_calendar_events",
        "description": "List calendar events for a date range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User calendar"},
                "start_date": {"type": "string", "description": "Start date (ISO format, default: today)"},
                "end_date": {"type": "string", "description": "End date (ISO format, default: 7 days from start)"},
                "top": {"type": "integer", "description": "Max events (default: 50)"}
            }
        }
    },
    {
        "name": "create_event",
        "description": "Create a calendar event",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User calendar"},
                "subject": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime (ISO format)"},
                "end": {"type": "string", "description": "End datetime (ISO format)"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                "location": {"type": "string", "description": "Location"},
                "body": {"type": "string", "description": "Event description"},
                "is_online": {"type": "boolean", "description": "Create Teams meeting"}
            },
            "required": ["subject", "start", "end"]
        }
    },
    {
        "name": "get_availability",
        "description": "Check free/busy availability for users",
        "inputSchema": {
            "type": "object",
            "properties": {
                "emails": {"type": "array", "items": {"type": "string"}, "description": "User emails to check"},
                "start": {"type": "string", "description": "Start datetime (ISO)"},
                "end": {"type": "string", "description": "End datetime (ISO)"}
            },
            "required": ["emails", "start", "end"]
        }
    },
    {
        "name": "list_users",
        "description": "List users in the organization",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search by name or email"},
                "top": {"type": "integer", "description": "Max results (default: 50)"}
            }
        }
    },
    {
        "name": "get_user",
        "description": "Get user profile details",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "User email or ID"}
            },
            "required": ["user"]
        }
    }
]


# ============ TOOL IMPLEMENTATIONS ============

def read_emails(user=None, folder="inbox", top=10, unread_only=False, search=None):
    """Read emails from inbox"""
    user = user or DEFAULT_USER
    params = [f"$top={top}", "$select=id,subject,from,receivedDateTime,bodyPreview,isRead"]
    params.append("$orderby=receivedDateTime desc")
    
    filters = []
    if unread_only:
        filters.append("isRead eq false")
    if search:
        params.append(f'$search="{search}"')
    if filters:
        params.append(f"$filter={' and '.join(filters)}")
    
    endpoint = f"/mailFolders/{folder}/messages?{'&'.join(params)}"
    result = graph_request("GET", endpoint, user=user)
    
    if "value" in result:
        return {
            "count": len(result["value"]),
            "emails": [{
                "id": m["id"],
                "subject": m.get("subject", "(no subject)"),
                "from": m.get("from", {}).get("emailAddress", {}).get("address", "unknown"),
                "from_name": m.get("from", {}).get("emailAddress", {}).get("name", ""),
                "date": m.get("receivedDateTime"),
                "preview": m.get("bodyPreview", "")[:200],
                "is_read": m.get("isRead", False)
            } for m in result["value"]]
        }
    return result


def get_email(message_id, user=None):
    """Get full email by ID"""
    user = user or DEFAULT_USER
    endpoint = f"/messages/{message_id}?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments"
    result = graph_request("GET", endpoint, user=user)
    
    if "id" in result:
        return {
            "id": result["id"],
            "subject": result.get("subject"),
            "from": result.get("from", {}).get("emailAddress", {}),
            "to": [r.get("emailAddress", {}) for r in result.get("toRecipients", [])],
            "cc": [r.get("emailAddress", {}) for r in result.get("ccRecipients", [])],
            "date": result.get("receivedDateTime"),
            "body": result.get("body", {}).get("content", ""),
            "has_attachments": result.get("hasAttachments", False)
        }
    return result


def send_email(to, subject, body, user=None, cc=None, bcc=None, is_html=False, importance="normal", attachments=None):
    """Send an email"""
    user = user or DEFAULT_USER

    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML" if is_html else "Text",
                "content": body
            },
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            "importance": importance
        }
    }

    if cc:
        message["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
    if bcc:
        message["message"]["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]
    if attachments:
        message["message"]["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": att["name"],
                "contentType": att.get("content_type", "application/octet-stream"),
                "contentBytes": att["content_bytes"]
            }
            for att in attachments
        ]

    result = graph_request("POST", "/sendMail", user=user, json=message)
    return {"success": True, "message": f"Email sent to {', '.join(to)}"}


def reply_email(message_id, body, user=None, reply_all=False):
    """Reply to an email"""
    user = user or DEFAULT_USER
    action = "replyAll" if reply_all else "reply"
    
    result = graph_request("POST", f"/messages/{message_id}/{action}", user=user, json={
        "comment": body
    })
    return {"success": True, "action": action}


def search_emails(query, user=None, top=25):
    """Search emails"""
    user = user or DEFAULT_USER
    endpoint = f'/messages?$search="{query}"&$top={top}&$select=id,subject,from,receivedDateTime,bodyPreview'
    result = graph_request("GET", endpoint, user=user)
    
    if "value" in result:
        return {
            "count": len(result["value"]),
            "emails": [{
                "id": m["id"],
                "subject": m.get("subject", "(no subject)"),
                "from": m.get("from", {}).get("emailAddress", {}).get("address", "unknown"),
                "date": m.get("receivedDateTime"),
                "preview": m.get("bodyPreview", "")[:200]
            } for m in result["value"]]
        }
    return result


def list_calendar_events(user=None, start_date=None, end_date=None, top=50):
    """List calendar events"""
    user = user or DEFAULT_USER
    
    if not start_date:
        start_date = datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")
    if not end_date:
        end_dt = datetime.utcnow() + timedelta(days=7)
        end_date = end_dt.strftime("%Y-%m-%dT23:59:59Z")
    
    endpoint = f"/calendarView?startDateTime={start_date}&endDateTime={end_date}&$top={top}&$select=id,subject,start,end,location,attendees,isOnlineMeeting,onlineMeetingUrl"
    result = graph_request("GET", endpoint, user=user)
    
    if "value" in result:
        return {
            "count": len(result["value"]),
            "events": [{
                "id": e["id"],
                "subject": e.get("subject"),
                "start": e.get("start", {}).get("dateTime"),
                "end": e.get("end", {}).get("dateTime"),
                "location": e.get("location", {}).get("displayName"),
                "attendees": [a.get("emailAddress", {}).get("address") for a in e.get("attendees", [])],
                "is_online": e.get("isOnlineMeeting", False),
                "teams_url": e.get("onlineMeetingUrl")
            } for e in result["value"]]
        }
    return result


def create_event(subject, start, end, user=None, attendees=None, location=None, body=None, is_online=False):
    """Create calendar event"""
    user = user or DEFAULT_USER
    
    event = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"}
    }
    
    if attendees:
        event["attendees"] = [{"emailAddress": {"address": addr}, "type": "required"} for addr in attendees]
    if location:
        event["location"] = {"displayName": location}
    if body:
        event["body"] = {"contentType": "Text", "content": body}
    if is_online:
        event["isOnlineMeeting"] = True
        event["onlineMeetingProvider"] = "teamsForBusiness"
    
    result = graph_request("POST", "/events", user=user, json=event)
    
    if "id" in result:
        return {
            "success": True,
            "event_id": result["id"],
            "subject": result.get("subject"),
            "teams_url": result.get("onlineMeeting", {}).get("joinUrl") if is_online else None
        }
    return result


def get_availability(emails, start, end):
    """Check free/busy availability"""
    token = get_access_token()
    
    body = {
        "schedules": emails,
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 30
    }
    
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{GRAPH_BASE}/users/{DEFAULT_USER}/calendar/getSchedule",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body
        )
        result = response.json()
    
    if "value" in result:
        return {
            "schedules": [{
                "email": s.get("scheduleId"),
                "availability": s.get("availabilityView"),
                "busy_slots": [{
                    "start": slot.get("start", {}).get("dateTime"),
                    "end": slot.get("end", {}).get("dateTime"),
                    "status": slot.get("status")
                } for slot in s.get("scheduleItems", [])]
            } for s in result["value"]]
        }
    return result


def list_users(search=None, top=50):
    """List organization users"""
    token = get_access_token()
    
    params = [f"$top={top}", "$select=id,displayName,mail,jobTitle,department"]
    if search:
        params.append(f'$search="displayName:{search}" OR "mail:{search}"')
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if search:
        headers["ConsistencyLevel"] = "eventual"
    
    with httpx.Client(timeout=30) as client:
        response = client.get(f"{GRAPH_BASE}/users?{'&'.join(params)}", headers=headers)
        result = response.json()
    
    if "value" in result:
        return {
            "count": len(result["value"]),
            "users": [{
                "id": u["id"],
                "name": u.get("displayName"),
                "email": u.get("mail"),
                "title": u.get("jobTitle"),
                "department": u.get("department")
            } for u in result["value"] if u.get("mail")]
        }
    return result


def get_user(user):
    """Get user profile"""
    token = get_access_token()
    
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{GRAPH_BASE}/users/{user}?$select=id,displayName,mail,jobTitle,department,officeLocation,mobilePhone,businessPhones",
            headers={"Authorization": f"Bearer {token}"}
        )
        result = response.json()
    
    if "id" in result:
        return {
            "id": result["id"],
            "name": result.get("displayName"),
            "email": result.get("mail"),
            "title": result.get("jobTitle"),
            "department": result.get("department"),
            "office": result.get("officeLocation"),
            "mobile": result.get("mobilePhone"),
            "phone": result.get("businessPhones", [None])[0]
        }
    return result


# Tool dispatcher
TOOL_MAP = {
    "read_emails": read_emails,
    "get_email": get_email,
    "send_email": send_email,
    "reply_email": reply_email,
    "search_emails": search_emails,
    "list_calendar_events": list_calendar_events,
    "create_event": create_event,
    "get_availability": get_availability,
    "list_users": list_users,
    "get_user": get_user
}


# ============ ROUTES ============

@app.route("/health", methods=["GET"])
def health():
    """Health check"""
    try:
        token = get_access_token()
        return jsonify({
            "status": "healthy",
            "service": "m365-mcp",
            "authenticated": True,
            "default_user": DEFAULT_USER,
            "tools": len(TOOLS)
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


@app.route("/mcp", methods=["POST"])
def mcp_handler():
    """MCP protocol handler"""
    data = request.json or {}
    method = data.get("method")
    
    if method == "initialize":
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "m365-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}}
            }
        })
    
    elif method == "tools/list":
        return jsonify({
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "result": {"tools": TOOLS}
        })
    
    elif method == "tools/call":
        tool_name = data.get("params", {}).get("name")
        arguments = data.get("params", {}).get("arguments", {})
        
        if tool_name not in TOOL_MAP:
            return jsonify({
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            })
        
        try:
            result = TOOL_MAP[tool_name](**arguments)
            return jsonify({
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}
            })
        except Exception as e:
            return jsonify({
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {"code": -32000, "message": str(e)}
            })
    
    return jsonify({
        "jsonrpc": "2.0",
        "id": data.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
