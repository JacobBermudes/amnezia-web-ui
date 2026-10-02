#!/usr/bin/env python3
import os
from flask import Flask
from flask_socketio import SocketIO

# Импортируем наши модули
from config import *
from manager import AmneziaManager
from routes import register_routes

print(f"Base directory: {BASE_DIR}")
print(f"Template directory: {TEMPLATE_DIR}")
print(f"Static directory: {STATIC_DIR}")
print("=== Environment Configuration ===")
print(f"NGINX_PORT: {NGINX_PORT}")
print(f"AUTO_START_SERVERS: {AUTO_START_SERVERS}")
print(f"DEFAULT_MTU: {DEFAULT_MTU}")
print(f"DEFAULT_SUBNET: {DEFAULT_SUBNET}")
print(f"DEFAULT_PORT: {DEFAULT_PORT}")
print(f"DEFAULT_DNS: {DEFAULT_DNS}")
print(f"DNS_SERVERS: {DNS_SERVERS}")
print("==================================")
print("Fixed Configuration:")
print(f"WEB_UI_PORT: {WEB_UI_PORT} (internal)")
print(f"CONFIG_DIR: {CONFIG_DIR}")
print(f"ENABLE_OBFUSCATION: {ENABLE_OBFUSCATION}")
print("==================================")

print(f"Templates exist: {os.path.exists(TEMPLATE_DIR)}")
print(f"Static exist: {os.path.exists(STATIC_DIR)}")
if os.path.exists(TEMPLATE_DIR):
    print(f"Template files: {os.listdir(TEMPLATE_DIR)}")
if os.path.exists(STATIC_DIR):
    print(f"Static files: {os.listdir(STATIC_DIR)}")

# Инициализация Flask
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.urandom(24)

# Инициализация Socket.IO
socketio = SocketIO(
    app,
    async_mode='eventlet',
    cors_allowed_origins="*",
    path='/socket.io',
    ping_timeout=10,
    ping_interval=15,
    allow_upgrades=True,
    http_compression=True
)

# Инициализация ядра менеджера
amnezia_manager = AmneziaManager(socketio)

# Регистрация всех API-роутов и вебсокетов
register_routes(app, socketio, amnezia_manager)

if __name__ == '__main__':
    print(f"AmneziaWG Web UI starting...")
    print(f"Configuration:")
    print(f"  NGINX Port: {NGINX_PORT}")
    print(f"  Auto-start: {AUTO_START_SERVERS}")
    print(f"  Default MTU: {DEFAULT_MTU}")
    print(f"  Default Subnet: {DEFAULT_SUBNET}")
    print(f"  Default Port: {DEFAULT_PORT}")
    print(f"Detected public IP: {amnezia_manager.public_ip}")

    if AUTO_START_SERVERS:
        print("Auto-starting existing servers...")

    socketio.run(app, host='0.0.0.0', port=WEB_UI_PORT, debug=False, allow_unsafe_werkzeug=True)