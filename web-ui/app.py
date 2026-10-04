#!/usr/bin/env python3
import os
from flask import Flask
from flask_socketio import SocketIO

# Импортируем наши модули
import config  # Импортируем конфигурацию
from manager import AmneziaManager
from routes import register_routes

print(f"Base directory: {config.BASE_DIR}")
print(f"Template directory: {config.TEMPLATE_DIR}")
print(f"Static directory: {config.STATIC_DIR}")
print("=== Environment Configuration ===")
print(f"NGINX_PORT: {config.NGINX_PORT}")
print(f"AUTO_START_SERVERS: {config.AUTO_START_SERVERS}")
print(f"DEFAULT_MTU: {config.DEFAULT_MTU}")
print(f"DEFAULT_SUBNET: {config.DEFAULT_SUBNET}")
print(f"DEFAULT_PORT: {config.DEFAULT_PORT}")
print(f"DEFAULT_DNS: {config.DEFAULT_DNS}")
print(f"DNS_SERVERS: {config.DNS_SERVERS}")
print("==================================")
print("Fixed Configuration:")
print(f"WEB_UI_PORT: {config.WEB_UI_PORT} (internal)")
print(f"CONFIG_DIR: {config.CONFIG_DIR}")
print(f"ENABLE_OBFUSCATION: {config.ENABLE_OBFUSCATION}")
print("==================================")

print(f"Templates exist: {os.path.exists(config.TEMPLATE_DIR)}")
print(f"Static exist: {os.path.exists(config.STATIC_DIR)}")
if os.path.exists(config.TEMPLATE_DIR):
    print(f"Template files: {os.listdir(config.TEMPLATE_DIR)}")
if os.path.exists(config.STATIC_DIR):
    print(f"Static files: {os.listdir(config.STATIC_DIR)}")

# Инициализация Flask
app = Flask(__name__, template_folder=config.TEMPLATE_DIR, static_folder=config.STATIC_DIR)
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
    print(f"  NGINX Port: {config.NGINX_PORT}")
    print(f"  Auto-start: {config.AUTO_START_SERVERS}")
    print(f"  Default MTU: {config.DEFAULT_MTU}")
    print(f"  Default Subnet: {config.DEFAULT_SUBNET}")
    print(f"  Default Port: {config.DEFAULT_PORT}")
    print(f"Detected public IP: {amnezia_manager.public_ip}")

    if config.AUTO_START_SERVERS:
        print("Auto-starting existing servers...")

    socketio.run(app, host='0.0.0.0', port=config.WEB_UI_PORT, debug=False, allow_unsafe_werkzeug=True)