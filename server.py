from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
from datetime import datetime

# File paths (Render uses /tmp for free tier)
MESSAGES_FILE = '/tmp/messages.json' if os.path.exists('/tmp') else 'messages.json'
USERS_FILE = '/tmp/users.json' if os.path.exists('/tmp') else 'users.json'

# Load data
MESSAGES = []
USERS = {}

if os.path.exists(MESSAGES_FILE):
    with open(MESSAGES_FILE, 'r') as f:
        MESSAGES = json.load(f)

if os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'r') as f:
        USERS = json.load(f)

def hash_password(password):
    import hashlib, secrets
    salt = secrets.token_hex(16)
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest() + ":" + salt

def verify_password(password, stored):
    hash_part, salt = stored.split(":")
    return hash_part == hashlib.sha256(f"{password}{salt}".encode()).hexdigest()

class Handler(SimpleHTTPRequestHandler):
    
    def do_GET(self):
        if self.path == '/':
            self.path = '/index.html'
        elif self.path == '/api/messages':
            self.send_json(MESSAGES[-100:])
            return
        return SimpleHTTPRequestHandler.do_GET(self)
    
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
            else:
                self.send_json({'error': 'Unknown'}, 404)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
    
    def handle_signup(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if len(username) < 3:
            self.send_json({'error': 'Username too short'}, 400)
            return
        if len(password) < 4:
            self.send_json({'error': 'Password too short'}, 400)
            return
        if username in USERS:
            self.send_json({'error': 'Username exists'}, 400)
            return
        
        USERS[username] = hash_password(password)
        with open(USERS_FILE, 'w') as f:
            json.dump(USERS, f)
        
        self.send_json({'success': True})
    
    def handle_login(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if username not in USERS:
            self.send_json({'error': 'Invalid credentials'}, 401)
            return
        
        if verify_password(password, USERS[username]):
            self.send_json({'success': True, 'username': username})
        else:
            self.send_json({'error': 'Invalid credentials'}, 401)
    
    def handle_send(self, data):
        msg = {
            'username': data.get('username', ''),
            'text': data.get('text', '')[:500],
            'time': datetime.now().strftime('%I:%M %p')
        }
        MESSAGES.append(msg)
        
        # Keep last 500
        while len(MESSAGES) > 500:
            MESSAGES.pop(0)
        
        with open(MESSAGES_FILE, 'w') as f:
            json.dump(MESSAGES, f)
        
        self.send_json({'success': True})
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        pass

print("=" * 50)
print("💬 WAVO MESSENGER ON RENDER")
print("=" * 50)
print(f"Users: {len(USERS)} | Messages: {len(MESSAGES)}")
print("=" * 50)

HTTPServer(('0.0.0.0', 10000), Handler).serve_forever()