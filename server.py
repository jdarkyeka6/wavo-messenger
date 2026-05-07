from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import hashlib
import secrets
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse
import time
import uuid
import base64

# ========== FILE PATHS (JSON files instead of .db) ==========
USERS_FILE = 'users.json'
MESSAGES_FILE = 'messages.json'
GROUPS_FILE = 'groups.json'
PROFILES_FILE = 'profiles.json'

# ========== DATA STRUCTURES ==========
USERS = {}        # username -> {'password_hash': str, 'created_at': str}
MESSAGES = []     # list of message objects
GROUPS = {}       # group_id -> {'name': str, 'members': list, 'created_by': str, 'created_at': str}
PROFILES = {}     # username -> {'avatar': str (base64), 'theme': str, 'bio': str}

# ========== LOAD DATA FROM JSON FILES ==========
def load_data():
    global USERS, MESSAGES, GROUPS, PROFILES
    
    # Load users.json
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                USERS = json.load(f)
            print(f"✅ Loaded {len(USERS)} users from {USERS_FILE}")
        except:
            print(f"⚠️ Could not read {USERS_FILE}, starting fresh")
            USERS = {}
    else:
        print(f"📝 {USERS_FILE} not found, will create when first user signs up")
        USERS = {}
    
    # Load messages.json
    if os.path.exists(MESSAGES_FILE):
        try:
            with open(MESSAGES_FILE, 'r') as f:
                MESSAGES = json.load(f)
            print(f"✅ Loaded {len(MESSAGES)} messages from {MESSAGES_FILE}")
        except:
            MESSAGES = []
    else:
        MESSAGES = []
    
    # Load groups.json
    if os.path.exists(GROUPS_FILE):
        try:
            with open(GROUPS_FILE, 'r') as f:
                GROUPS = json.load(f)
            print(f"✅ Loaded {len(GROUPS)} groups from {GROUPS_FILE}")
        except:
            GROUPS = {}
    else:
        GROUPS = {}
    
    # Load profiles.json
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, 'r') as f:
                PROFILES = json.load(f)
            print(f"✅ Loaded {len(PROFILES)} profiles from {PROFILES_FILE}")
        except:
            PROFILES = {}
    else:
        PROFILES = {}

def save_users():
    with open(USERS_FILE, 'w') as f:
        json.dump(USERS, f, indent=2)
    print(f"💾 Saved {len(USERS)} users to {USERS_FILE}")

def save_messages():
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(MESSAGES[-10000:], f, indent=2)
    print(f"💾 Saved {len(MESSAGES)} messages to {MESSAGES_FILE}")

def save_groups():
    with open(GROUPS_FILE, 'w') as f:
        json.dump(GROUPS, f, indent=2)
    print(f"💾 Saved {len(GROUPS)} groups to {GROUPS_FILE}")

def save_profiles():
    with open(PROFILES_FILE, 'w') as f:
        json.dump(PROFILES, f, indent=2)
    print(f"💾 Saved {len(PROFILES)} profiles to {PROFILES_FILE}")

# Load all data at startup
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

# Track typing status
typing_users = {}  # username -> {'chat_id': str, 'timestamp': float}

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
            
            # Mark messages as read
            for msg in filtered:
                if msg.get('to') == current_user and not msg.get('read', False):
                    msg['read'] = True
            save_messages()
            
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
            unread_counts = {}
            for msg in MESSAGES:
                if msg['type'] == 'dm':
                    if msg['from'] == current_user:
                        dm_partners.add(msg['to'])
                    elif msg['to'] == current_user:
                        dm_partners.add(msg['from'])
                        if not msg.get('read', False):
                            unread_counts[msg['from']] = unread_counts.get(msg['from'], 0) + 1
            
            dms = [{'type': 'dm', 'id': p, 'name': p, 'unread': unread_counts.get(p, 0)} for p in dm_partners]
            
            # Get groups user is in
            user_groups = []
            group_unread = {}
            for msg in MESSAGES:
                if msg['type'] == 'group' and msg.get('group_id'):
                    if current_user in GROUPS.get(msg['group_id'], {}).get('members', []):
                        if msg.get('to') == current_user and not msg.get('read', False):
                            group_unread[msg['group_id']] = group_unread.get(msg['group_id'], 0) + 1
            
            for gid, group in GROUPS.items():
                if current_user in group.get('members', []):
                    user_groups.append({
                        'type': 'group',
                        'id': gid,
                        'name': group['name'],
                        'unread': group_unread.get(gid, 0)
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
                        avatar = PROFILES.get(username, {}).get('avatar', '')
                        results.append({'username': username, 'avatar': avatar[:50] if avatar else ''})
                self.send_json(results[:20])
                return
        
        # API: Get group members
        elif parsed.path == '/api/group_members':
            params = parse_qs(parsed.query)
            group_id = params.get('group_id', [''])[0]
            
            if group_id in GROUPS:
                members_with_avatars = []
                for m in GROUPS[group_id].get('members', []):
                    avatar = PROFILES.get(m, {}).get('avatar', '')
                    members_with_avatars.append({'username': m, 'avatar': avatar[:50] if avatar else ''})
                self.send_json(members_with_avatars)
            else:
                self.send_json([])
            return
        
        # API: Get typing status
        elif parsed.path == '/api/typing':
            params = parse_qs(parsed.query)
            chat_id = params.get('chat_id', [''])[0]
            current_user = params.get('current', [''])[0]
            
            typing_list = []
            current_time = time.time()
            for user, data in typing_users.items():
                if data['chat_id'] == chat_id and user != current_user:
                    if current_time - data['timestamp'] < 3:
                        typing_list.append(user)
            self.send_json({'typing': typing_list})
            return
        
        # API: Get user profile
        elif parsed.path == '/api/profile':
            params = parse_qs(parsed.query)
            username = params.get('username', [''])[0]
            
            profile = PROFILES.get(username, {})
            self.send_json({
                'username': username,
                'avatar': profile.get('avatar', ''),
                'theme': profile.get('theme', 'light'),
                'bio': profile.get('bio', '')
            })
            return
        
        # API: Export chat
        elif parsed.path == '/api/export':
            params = parse_qs(parsed.query)
            current_user = params.get('current', [''])[0]
            chat_type = params.get('type', [''])[0]
            chat_id = params.get('id', [''])[0]
            
            export_messages = []
            for msg in MESSAGES:
                if chat_type == 'dm':
                    if (msg['type'] == 'dm' and 
                        ((msg['from'] == current_user and msg['to'] == chat_id) or
                         (msg['from'] == chat_id and msg['to'] == current_user))):
                        export_messages.append(msg)
                elif chat_type == 'group':
                    if msg['type'] == 'group' and msg['group_id'] == chat_id:
                        export_messages.append(msg)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Content-Disposition', f'attachment; filename="chat_export_{chat_id}.json"')
            self.end_headers()
            self.wfile.write(json.dumps(export_messages, indent=2).encode())
            return
        
        # API: Health check
        elif parsed.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
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
            elif self.path == '/api/typing':
                self.handle_typing(data)
            elif self.path == '/api/update_profile':
                self.handle_update_profile(data)
            elif self.path == '/api/upload_file':
                self.handle_upload_file(data)
            elif self.path == '/api/voice_message':
                self.handle_voice_message(data)
            elif self.path == '/api/delete_message':
                self.handle_delete_message(data)
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
        
        # Create default profile
        if username not in PROFILES:
            PROFILES[username] = {'avatar': '', 'theme': 'light', 'bio': ''}
            save_profiles()
        
        self.send_json({'success': True, 'username': username})
    
    def handle_login(self, data):
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if username not in USERS:
            self.send_json({'error': 'Invalid username or password'}, 401)
            return
        
        if verify_password(password, USERS[username]['password_hash']):
            # Ensure profile exists
            if username not in PROFILES:
                PROFILES[username] = {'avatar': '', 'theme': 'light', 'bio': ''}
                save_profiles()
            
            self.send_json({'success': True, 'username': username})
        else:
            self.send_json({'error': 'Invalid username or password'}, 401)
    
    def handle_send(self, data):
        msg_type = data.get('type', 'dm')
        from_user = data.get('from', '')
        text = data.get('text', '')[:1000]
        
        message = {
            'id': str(uuid.uuid4())[:8],
            'type': msg_type,
            'from': from_user,
            'text': text,
            'time': datetime.now().strftime('%I:%M %p'),
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        
        # Handle file attachments
        if data.get('file'):
            message['file'] = data.get('file')
            message['file_type'] = data.get('file_type', 'image')
        
        # Handle voice message
        if data.get('voice'):
            message['voice'] = data.get('voice')
            message['voice_duration'] = data.get('voice_duration', 0)
        
        if msg_type == 'dm':
            to_user = data.get('to', '')
            message['to'] = to_user
        else:
            group_id = data.get('group_id', '')
            message['group_id'] = group_id
            message['to'] = 'group'
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
    
    def handle_typing(self, data):
        username = data.get('username', '')
        chat_id = data.get('chat_id', '')
        is_typing = data.get('is_typing', False)
        
        if is_typing:
            typing_users[username] = {'chat_id': chat_id, 'timestamp': time.time()}
        else:
            typing_users.pop(username, None)
        
        self.send_json({'success': True})
    
    def handle_update_profile(self, data):
        username = data.get('username', '')
        
        if username not in PROFILES:
            PROFILES[username] = {}
        
        if 'avatar' in data:
            PROFILES[username]['avatar'] = data['avatar']
        if 'theme' in data:
            PROFILES[username]['theme'] = data['theme']
        if 'bio' in data:
            PROFILES[username]['bio'] = data['bio'][:200]
        
        save_profiles()
        self.send_json({'success': True})
    
    def handle_upload_file(self, data):
        self.send_json({'success': True, 'file_id': str(uuid.uuid4())[:8]})
    
    def handle_voice_message(self, data):
        self.send_json({'success': True})
    
    def handle_delete_message(self, data):
        message_id = data.get('message_id', '')
        username = data.get('username', '')
        
        global MESSAGES
        for i, msg in enumerate(MESSAGES):
            if msg.get('id') == message_id and msg.get('from') == username:
                msg['text'] = '[Message deleted]'
                msg['deleted'] = True
                save_messages()
                break
        
        self.send_json({'success': True})
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        pass

# ========== START SERVER ==========
print("=" * 60)
print("💬 WAVO MESSENGER - JSON STORAGE")
print("=" * 60)
print(f"📁 Data files in: {os.getcwd()}")
print(f"   ├── {USERS_FILE} (usernames + hashed passwords)")
print(f"   ├── {MESSAGES_FILE} (all chat messages)")
print(f"   ├── {GROUPS_FILE} (group chats)")
print(f"   └── {PROFILES_FILE} (avatars, themes, bios)")
print("=" * 60)
print(f"📊 Current stats:")
print(f"   👥 Users: {len(USERS)}")
print(f"   💬 Messages: {len(MESSAGES)}")
print(f"   👥 Groups: {len(GROUPS)}")
print(f"   🖼️ Profiles: {len(PROFILES)}")
print("=" * 60)
print("🌐 Server running!")
print("=" * 60)

port = int(os.environ.get('PORT', 10000))
HTTPServer(('0.0.0.0', port), Handler).serve_forever()