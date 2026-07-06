#!/usr/bin/env python3
"""
V1 Chat Client - Connects to server, joins rooms, chats.
No P2P. No peer connections. Just server and rooms.
"""

import socket, threading, time, json, os, sys, hashlib, base64, secrets, ssl
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog

class SimpleEncryptor:
    def __init__(self, password):
        self.key = hashlib.sha256(password.encode()).digest()
    
    def encrypt(self, plaintext):
        try:
            nonce = secrets.token_hex(8)
            keystream = hashlib.sha256(self.key + nonce.encode()).digest()
            pt = plaintext.encode('utf-8')
            ct = bytes([p ^ keystream[i % len(keystream)] for i, p in enumerate(pt)])
            return base64.b64encode(nonce.encode() + b':' + ct).decode()
        except: return None
    
    def decrypt(self, text):
        try:
            decoded = base64.b64decode(text.encode())
            parts = decoded.split(b':', 1)
            if len(parts) != 2:
                return None
            nonce = parts[0].decode()
            ct = parts[1]
            keystream = hashlib.sha256(self.key + nonce.encode()).digest()
            pt = bytes([c ^ keystream[i % len(keystream)] for i, c in enumerate(ct)])
            return pt.decode('utf-8')
        except: return None

class ChatClient:
    def __init__(self, root):
        self.use_tls = False  # Set to True for TLS connections
        self.root = root
        self.root.title("V1 Chat Client")
        self.root.geometry("700x500")
        self.root.configure(bg="#1e1e1e")
        
        self.sock = None
        self.connected = False
        self.peer_id = None
        self.encryptor = None
        self.password = None
        self.current_room = None
        self.beep_enabled = True
        self.beep_volume = 50  # 0-100
        
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def _build_ui(self):
        # Top bar
        top = tk.Frame(self.root, bg="#2d2d2d", height=30)
        top.pack(fill=tk.X)
        
        # Connect/Disconnect button
        self.conn_btn = tk.Button(top, text="Connect", command=self._toggle_connection,
                                   bg="#0e639c", fg="white", font=("Arial", 9, "bold"),
                                   relief=tk.FLAT, padx=15, cursor="hand2")
        self.conn_btn.pack(side=tk.LEFT, padx=10, pady=2)
        
        self.status_lbl = tk.Label(top, text="Disconnected", bg="#2d2d2d", fg="#f44747", font=("Arial", 10))
        self.status_lbl.pack(side=tk.LEFT, padx=5)
        self.room_lbl = tk.Label(top, text="", bg="#2d2d2d", fg="#4ec9b0", font=("Arial", 10))
        self.room_lbl.pack(side=tk.RIGHT, padx=10)
        
        # Beep controls
        self.beep_btn = tk.Button(top, text="🔔", command=self._toggle_beep,
                                   bg="#2d2d2d", fg="#4ec9b0", font=("Arial", 10),
                                   relief=tk.FLAT, padx=5, cursor="hand2")
        self.beep_btn.pack(side=tk.RIGHT, padx=2)
        
        self.vol_scale = tk.Scale(top, from_=0, to=100, orient=tk.HORIZONTAL,
                                   length=60, bg="#2d2d2d", fg="#4ec9b0",
                                   troughcolor="#1e1e1e", highlightthickness=0,
                                   command=self._set_volume)
        self.vol_scale.set(50)
        self.vol_scale.pack(side=tk.RIGHT, padx=5)
        
        # Chat display
        self.chat = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, bg="#1e1e1e", fg="#d4d4d4",
                                                font=("Consolas", 10), state=tk.DISABLED)
        self.chat.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.chat.tag_config("system", foreground="#888888")
        self.chat.tag_config("error", foreground="#f44747")
        self.chat.tag_config("encrypted", foreground="#4ec9b0")
        self.chat.tag_config("msg", foreground="#d4d4d4")
        self.chat.tag_config("me", foreground="#569cd6")
        self.chat.tag_config("highlight", foreground="#ffa500")
        
        # Command bar
        cmd_frame = tk.Frame(self.root, bg="#2d2d2d", height=30)
        cmd_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        tk.Label(cmd_frame, text="/", bg="#2d2d2d", fg="#4ec9b0", font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(5, 2))
        self.cmd_entry = tk.Entry(cmd_frame, bg="#1e1e1e", fg="#4ec9b0", insertbackground="#4ec9b0",
                                   font=("Consolas", 10), relief=tk.FLAT)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind("<Return>", self._run_cmd)
        self.cmd_entry.insert(0, "/help")
        tk.Button(cmd_frame, text="Run", command=self._run_cmd, bg="#0e639c", fg="white",
                 font=("Arial", 9), relief=tk.FLAT, padx=10).pack(side=tk.RIGHT, padx=5)
        
        # Message input
        msg_frame = tk.Frame(self.root, bg="#2d2d2d")
        msg_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.msg_entry = tk.Text(msg_frame, bg="#1e1e1e", fg="white", font=("Arial", 10),
                                  height=2, relief=tk.FLAT, padx=10, pady=5)
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.msg_entry.bind("<Return>", self._send_msg)
        tk.Button(msg_frame, text="Send", command=self._send_msg, bg="#0e639c", fg="white",
                 font=("Arial", 10, "bold"), relief=tk.FLAT, padx=15).pack(side=tk.RIGHT, padx=5)
    
    def _toggle_connection(self):
        """Connect or disconnect from server"""
        if self.connected:
            self._disconnect()
        else:
            self._connect()
    
    def _toggle_beep(self):
        self.beep_enabled = not self.beep_enabled
        if self.beep_enabled:
            self.beep_btn.config(text="🔔", fg="#4ec9b0")
        else:
            self.beep_btn.config(text="🔕", fg="#f44747")
    
    def _set_volume(self, val):
        self.beep_volume = int(val)
    
    def _beep(self):
        if self.beep_enabled:
            # Use terminal bell with volume control via frequency
            try:
                import os
                # Different volume levels by repeating bell
                times = max(1, self.beep_volume // 25)
                for _ in range(times):
                    print('\a', end='', flush=True)
            except:
                pass
    
    def _disconnect(self):
        """Disconnect from server"""
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.status_lbl.config(text="Disconnected", fg="#f44747")
        self.conn_btn.config(text="Connect", bg="#0e639c")
        self.room_lbl.config(text="")
        self.current_room = None
        self.beep_enabled = True
        self.beep_volume = 50  # 0-100
        self.log("Disconnected from server", "system")
    
    def _connect(self):
        addr = simpledialog.askstring("Connect", "Server address (IP:port):\n(Add :tls for TLS, e.g. 127.0.0.1:8765:tls)", parent=self.root)
        if not addr: return
        
        username = simpledialog.askstring("Username", "Choose a username (3-20 chars):", parent=self.root)
        if not username: return
        username = username.strip()
        if len(username) < 3 or len(username) > 20:
            messagebox.showerror("Invalid", "Username must be 3-20 characters")
            return
        
        pw = simpledialog.askstring("Password", "Enter password:", parent=self.root, show='*')
        if not pw: return
        
        self.password = pw
        self.encryptor = SimpleEncryptor(pw)
        self.peer_id = username
        
        try:
            parts = addr.split(':')
            host = parts[0]
            port = int(parts[1])
            self.use_tls = len(parts) > 2 and parts[2].lower() == 'tls'
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((host, int(port)))
            
            # Wrap with TLS if enabled
            if self.use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE  # Accept self-signed cert
                self.sock = context.wrap_socket(self.sock, server_hostname=host)
            
            reg = {'type': 'register', 'username': username, 'password': pw}
            self._send(reg)
            
            resp = self._recv()
            if resp and resp.get('type') == 'welcome':
                self.connected = True
                self.status_lbl.config(text=f"{self.peer_id} ({resp.get('role', 'user')})", fg="#4ec9b0")
                self.conn_btn.config(text="Disconnect", bg="#8b0000")
                self.log(f"✅ {resp.get('message', 'Connected!')}", "system")
                threading.Thread(target=self._recv_loop, daemon=True).start()
            else:
                self.log("❌ Connection failed", "error")
                self.sock.close()
        except Exception as e:
            self.log(f"❌ {e}", "error")
    
    def _send(self, data):
        if not self.sock: return
        try:
            plain = json.dumps(data)
            if self.encryptor:
                enc = self.encryptor.encrypt(plain)
                if enc:
                    self.sock.send((json.dumps({'type': 'encrypted', 'data': enc}) + '\n').encode())
                    return
            self.sock.send((plain + '\n').encode())
        except: pass
    
    def _recv(self):
        if not self.sock: return None
        try:
            self.sock.settimeout(2)
            data = self.sock.recv(4096)
            if not data: return None
            msg = json.loads(data.decode().strip())
            if msg.get('type') == 'encrypted' and self.encryptor:
                dec = self.encryptor.decrypt(msg['data'])
                if dec: return json.loads(dec)
            return msg
        except: return None
    
    def _recv_loop(self):
        buf = ""
        while self.connected:
            try:
                self.sock.settimeout(1)
                data = self.sock.recv(4096)
                if not data: break
                buf += data.decode()
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    if line.strip():
                        try:
                            msg = json.loads(line.strip())
                            if msg.get('type') == 'encrypted' and self.encryptor:
                                dec = self.encryptor.decrypt(msg['data'])
                                if dec: msg = json.loads(dec)
                            self.root.after(0, self._handle, msg)
                        except: pass
            except socket.timeout: continue
            except: break
        self.root.after(0, self._disconnected)
    
    def _handle(self, msg):
        t = msg.get('type', '')
        if t == 'chat_message':
            sender = msg.get('from', '?')
            content = msg.get('content', '')
            tag = "me" if sender == self.peer_id else "msg"
            self.log(f"{sender}: {content}", tag)
        elif t == 'cmd_result':
            r = msg.get('result', {})
            if r.get('success'):
                self.log(f"✅ {r.get('message', 'Done')}", "system")
                # Update room info if join/create
                if 'Joined:' in r.get('message', '') or 'Room created!' in r.get('message', ''):
                    self._update_room()
            elif 'error' in r:
                self.log(f"❌ {r['error']}", "error")
            elif 'message' in r:
                self.log(r['message'], "system")
        elif t == 'user_alert':
            self.log(msg.get('message', ''), "highlight")
            self._beep()
        
        elif t == 'user_joined':
            self.log(f"➕ {msg.get('message', '')}", "system")
        elif t == 'user_left':
            self.log(f"➖ {msg.get('message', '')}", "system")
    
    def _update_room(self):
        # Query server for current room
        if self.sock and self.connected:
            self._send({'type': 'command', 'command': '/whoami'})
    
    def _disconnected(self):
        self.connected = False
        self.sock = None
        self.status_lbl.config(text="Disconnected", fg="#f44747")
        self.conn_btn.config(text="Connect", bg="#0e639c")
        self.room_lbl.config(text="")
        self.current_room = None
        self.beep_enabled = True
        self.beep_volume = 50  # 0-100
        self.log("Connection lost", "error")
    
    def _run_cmd(self, event=None):
        cmd = self.cmd_entry.get().strip()
        if not cmd: return
        self.cmd_entry.delete(0, tk.END)
        # Don't show the command in chat
        
        if not cmd.startswith('/'):
            # Treat as message
            self.msg_entry.insert("1.0", cmd)
            self._send_msg()
            return
        
        if self.sock and self.connected:
            self._send({'type': 'command', 'command': cmd})
        else:
            self.log("Not connected", "error")
    
    def _send_msg(self, event=None):
        if not self.connected: return "break"
        txt = self.msg_entry.get("1.0", tk.END).strip()
        if not txt: return "break"
        
        if txt.startswith('/'):
            self.cmd_entry.delete(0, tk.END)
            self.cmd_entry.insert(0, txt)
            self._run_cmd()
            self.msg_entry.delete("1.0", tk.END)
            return "break"
        
        # Send as chat_message
        self._send({'type': 'chat_message', 'content': txt})
        self.msg_entry.delete("1.0", tk.END)
        
        # Show own message immediately
        timestamp = time.strftime("%H:%M:%S")
        self.chat.config(state=tk.NORMAL)
        self.chat.insert(tk.END, f"[{timestamp}] You: {txt}\n", "me")
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
        
        return "break"
    
    def log(self, msg, tag="system"):
        self.chat.config(state=tk.NORMAL)
        if tag in ("system", "error", "encrypted"):
            ts = datetime.now().strftime("%H:%M:%S")
            self.chat.insert(tk.END, f"[{ts}] {msg}\n", tag)
        else:
            self.chat.insert(tk.END, f"{msg}\n", tag)
        self.chat.see(tk.END)
        self.chat.config(state=tk.DISABLED)
    
    def on_close(self):
        self._disconnect()
        self.root.destroy()

def main():
    root = tk.Tk()
    ChatClient(root)
    root.mainloop()

if __name__ == "__main__":
    main()
