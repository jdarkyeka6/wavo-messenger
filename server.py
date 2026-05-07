from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import hashlib
import secrets
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse
import threading
import time
import uuid

# ========== FILE PATHS ==========
USERS_FILE = 'users.json'
MESSAGES_FILE = 'messages.json'
GROUPS_FILE = 'groups.json'

# ========== DATA STRUCTURES ==========
USERS = {}        # username -> {'password_hash': str, 'created_at': str}
MESSAGES = []     # list of message objects
GROUPS = {}       # group_id -> {'name': str, 'members': list, 'created_by': str, 'created_at': str}

# ========== LOAD DATA ==========
def load_data():
    global USERS, MESSAGES, GROUPS
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            USERS = json.load(f)
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, 'r') as f:
            MESSAGES = json.load(f)
    if os.path.exists(GROUPS_FILE):
        with open(GROUPS_FILE, 'r') as f:
            GROUPS = json.load(f)

def save_users():
    with open(USERS_FILE, 'w') as f:
        json.dump(USERS, f, indent=2)

def save_messages():
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(MESSAGES[-5000:], f, indent=2)

def save_groups():
    with open(GROUPS_FILE, 'w') as f:
        json.dump(GROUPS, f, indent=2)

load_data()

# ========== PASSWORD HASHING ==========
def hash_password(password):
    salt = secrets.token_hex(16)
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest() + ":" + salt

def verify_password(password, stored):
    try:
        hash_part, salt = stored.split(":")
        return hash_part == hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    except:
        return False

# ========== HTTP HANDLER ==========
class Handler(SimpleHTTPRequestHandler):
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        # Serve index.html
        if parsed.path == '/':
            self.path = '/index.html'
            return SimpleHTTPRequestHandler.do_GET(self)
        
        # API: Get messages for a chat
        elif parsed.path == '/api/messages':
            params = parse_qs(parsed.query)
            current_user = params.get('current', [''])[0]
            chat_type = params.get('type', [''])[0]
            chat_id = params.get('id', [''])[0]
            
            filtered = []
            for msg in MESSAGES:
                if chat_type == 'dm':
                    if (msg['type'] == 'dm' and 
                        ((msg['from'] == current_user and msg['to'] == chat_id) or
                         (msg['from'] == chat_id and msg['to'] == current_user))):
                        filtered.append(msg)
                elif chat_type == 'group':
                    if msg['type'] == 'group' and msg['group_id'] == chat_id:
                        filtered.append(msg)
            
            self.send_json(filtered[-200:])
            return
        
        # API: Get user's chats (DMs + Groups)
        elif parsed.path == '/api/chats':
            params = parse_qs(parsed.query)
            current_user = params.get('username', [''])[0]
            
            if not current_user:
                self.send_json({'error': 'No username provided'}, 400)
                return
            
            # Get unique DM partners
            dm_partners = set()
            for msg in MESSAGES:
                if msg['type'] == 'dm':
                    if msg['from'] == current_user:
                        dm_partners.add(msg['to'])
                    elif msg['to'] == current_user:
                        dm_partners.add(msg['from'])
            
            dms = [{'type': 'dm', 'id': p, 'name': p} for p in dm_partners]
            
            # Get groups user is in
            user_groups = []
            for gid, group in GROUPS.items():
                if current_user in group.get('members', []):
                    user_groups.append({
                        'type': 'group',
                        'id': gid,
                        'name': group['name']
                    })
            
            self.send_json({'dms': dms, 'groups': user_groups})
            return
        
        # API: Search users
        elif parsed.path == '/api/search_users':
            params = parse_qs(parsed.query)
            query = params.get('q', [''])[0]
            current_user = params.get('current', [''])[0]
            
            if query:
                results = []
                for username in USERS.keys():
                    if query.lower() in username.lower() and username != current_user:
                        results.append({'username': username})
                self.send_json(results[:20])
                return
        
        # API: Get group members
        elif parsed.path == '/api/group_members':
            params = parse_qs(parsed.query)
            group_id = params.get('group_id', [''])[0]
            
            if group_id in GROUPS:
                self.send_json(GROUPS[group_id].get('members', []))
            else:
                self.send_json([])
            return
        
        # Serve static files
        elif parsed.path.endswith('.html') or parsed.path.endswith('.css') or parsed.path.endswith('.js'):
            return SimpleHTTPRequestHandler.do_GET(self)
        
        else:
            self.send_json({'error': 'Not found'}, 404)
    
    def do_POST(self):
        try:
            length = int(self.headers['Content-Length'])
            data = json.loads(self.rfile.read(length))
            
            if self.path == '/api/signup':
                self.handle_signup(data)
            elif self.path == '/api/login':
                self.handle_login(data)
            elif self.path == '/api/send':
                self.handle_send(data)
            elif self.path == '/api/create_group':
                self.handle_create_group(data)
            elif self.path == '/api/add_to_group':
                self.handle_add_to_group(data)
            else:
                self.send_json({'error': 'Unknown endpoint'}, 404)
                
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def handle_signup(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            self.send_json({'error': 'Username must be 3-20 letters, numbers, or underscore'}, 400)
            return
        
        if len(password) < 4:
            self.send_json({'error': 'Password must be at least 4 characters'}, 400)
            return
        
        if username in USERS:
            self.send_json({'error': 'Username already exists'}, 400)
            return
        
        USERS[username] = {
            'password_hash': hash_password(password),
            'created_at': datetime.now().isoformat()
        }
        save_users()
        
        self.send_json({'success': True, 'username': username})
    
    def handle_login(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if username not in USERS:
            self.send_json({'error': 'Invalid username or password'}, 401)
            return
        
        if verify_password(password, USERS[username]['password_hash']):
            self.send_json({'success': True, 'username': username})
        else:
            self.send_json({'error': 'Invalid username or password'}, 401)
    
    def handle_send(self, data):
        msg_type = data.get('type', 'dm')  # 'dm' or 'group'
        from_user = data.get('from', '')
        text = data.get('text', '')[:1000]
        
        message = {
            'id': str(uuid.uuid4())[:8],
            'type': msg_type,
            'from': from_user,
            'text': text,
            'time': datetime.now().strftime('%I:%M %p'),
            'timestamp': datetime.now().isoformat()
        }
        
        if msg_type == 'dm':
            to_user = data.get('to', '')
            message['to'] = to_user
        else:
            group_id = data.get('group_id', '')
            message['group_id'] = group_id
            if group_id in GROUPS:
                message['group_name'] = GROUPS[group_id]['name']
        
        MESSAGES.append(message)
        save_messages()
        
        self.send_json({'success': True, 'message': message})
    
    def handle_create_group(self, data):
        group_name = data.get('name', '').strip()
        created_by = data.get('created_by', '')
        
        if not group_name:
            self.send_json({'error': 'Group name required'}, 400)
            return
        
        group_id = str(uuid.uuid4())[:8]
        GROUPS[group_id] = {
            'id': group_id,
            'name': group_name,
            'members': [created_by],
            'created_by': created_by,
            'created_at': datetime.now().isoformat()
        }
        save_groups()
        
        self.send_json({'success': True, 'group_id': group_id, 'group_name': group_name})
    
    def handle_add_to_group(self, data):
        group_id = data.get('group_id', '')
        username = data.get('username', '')
        
        if group_id not in GROUPS:
            self.send_json({'error': 'Group not found'}, 404)
            return
        
        if username not in GROUPS[group_id]['members']:
            GROUPS[group_id]['members'].append(username)
            save_groups()
        
        self.send_json({'success': True})
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        pass  # Suppress logs

# ========== START SERVER ==========
print("=" * 50)
print("💬 WAVO MESSENGER")
print("=" * 50)
print(f"✅ Users: {len(USERS)}")
print(f"✅ Messages: {len(MESSAGES)}")
print(f"✅ Groups: {len(GROUPS)}")
print("=" * 50)
print("🌐 Server running on port 10000")
print("=" * 50)

# Render uses port 10000 by default
port = int(os.environ.get('PORT', 10000))
HTTPServer(('0.0.0.0', port), Handler).serve_forever()