import os
import time
import tempfile
import subprocess
from flask import render_template, request, jsonify, send_file, send_from_directory
import config

def register_routes(app, socketio, amnezia_manager):

    @app.route('/')
    def index():
        print("Serving index.html")
        return render_template('index.html')

    @app.route('/static/<path:filename>')
    def static_files(filename):
        return send_from_directory(config.STATIC_DIR, filename)

    @app.route('/api/servers', methods=['POST'])
    def create_server():
        data = request.json
        server = amnezia_manager.create_wireguard_server(data)
        return jsonify(server)

    @app.route('/api/servers/<server_id>', methods=['DELETE'])
    def delete_server(server_id):
        if amnezia_manager.delete_server(server_id):
            return jsonify({"status": "deleted", "server_id": server_id})
        return jsonify({"error": "Server not found"}), 404

    @app.route('/api/servers/<server_id>/start', methods=['POST'])
    def start_server(server_id):
        if amnezia_manager.start_server(server_id):
            return jsonify({"status": "started"})
        return jsonify({"error": "Server not found or failed to start"}), 404

    @app.route('/api/servers/<server_id>/stop', methods=['POST'])
    def stop_server(server_id):
        if amnezia_manager.stop_server(server_id):
            return jsonify({"status": "stopped"})
        return jsonify({"error": "Server not found or failed to stop"}), 404

    @app.route('/api/servers/<server_id>/clients', methods=['GET'])
    def get_server_clients(server_id):
        clients = amnezia_manager.get_client_configs(server_id)
        return jsonify(clients)

    @app.route('/api/servers/<server_id>/clients', methods=['POST'])
    def add_client(server_id):
        data = request.json
        client_name = data.get('name', 'New Client')
        apply_i_settings = data.get('apply_i_settings', False)
        i_settings = data.get('i_settings', {})

        result = amnezia_manager.add_wireguard_client(server_id, client_name, apply_i_settings, i_settings)
        if result:
            client_config, config_content = result
            return jsonify({"client": client_config, "config": config_content})
        return jsonify({"error": "Server not found"}), 404

    @app.route('/api/servers/<server_id>/clients/<client_id>', methods=['DELETE'])
    def delete_client(server_id, client_id):
        if amnezia_manager.delete_client(server_id, client_id):
            return jsonify({"status": "deleted", "client_id": client_id})
        return jsonify({"error": "Client not found"}), 404

    @app.route('/api/servers/<server_id>/clients/<client_id>/i-settings', methods=['PUT'])
    def update_client_i_settings(server_id, client_id):
        data = request.json
        apply_i_settings = data.get('apply_i_settings')
        i_settings = data.get('i_settings', {})
        
        client, config_content = amnezia_manager.update_client_i_settings(server_id, client_id, apply_i_settings, i_settings)
        if client:
            return jsonify({"client": client, "config": config_content})
        return jsonify({"error": "Client not found"}), 404

    @app.route('/api/servers/<server_id>/clients/<client_id>/config')
    def download_client_config(server_id, client_id):
        client = amnezia_manager.config["clients"].get(client_id)
        if not client or client.get("server_id") != server_id:
            return jsonify({"error": "Client not found"}), 404
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404

        config_content = amnezia_manager.generate_wireguard_client_config(server, client, include_comments=True)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            f.write(config_content)
            temp_path = f.name
        filename = f"{client['name']}_{server['name']}.conf"
        return send_file(temp_path, as_attachment=True, download_name=filename)

    @app.route('/api/clients', methods=['GET'])
    def get_all_clients():
        clients = amnezia_manager.get_client_configs()
        return jsonify(clients)

    @app.route('/api/system/status')
    def system_status():
        status = {
            "awg_available": os.path.exists("/usr/bin/awg") and os.path.exists("/usr/bin/awg-quick"),
            "public_ip": amnezia_manager.public_ip,
            "total_servers": len(amnezia_manager.config["servers"]),
            "total_clients": len(amnezia_manager.config["clients"]),
            "active_servers": len([s for s in amnezia_manager.config["servers"]
                                 if amnezia_manager.get_server_status(s["id"]) == "running"]),
            "timestamp": time.time(),
            "environment": {
                "nginx_port": config.NGINX_PORT,
                "auto_start_servers": config.AUTO_START_SERVERS,
                "default_mtu": config.DEFAULT_MTU,
                "default_subnet": config.DEFAULT_SUBNET,
                "default_port": config.DEFAULT_PORT,
                "default_dns": config.DEFAULT_DNS
            }
        }
        return jsonify(status)

    @app.route('/api/system/refresh-ip')
    def refresh_ip():
        new_ip = amnezia_manager.detect_public_ip()
        amnezia_manager.public_ip = new_ip
        for server in amnezia_manager.config["servers"]:
            server["public_ip"] = new_ip
        amnezia_manager.save_config()
        return jsonify({"public_ip": new_ip})

    @app.route('/api/servers/<server_id>/config')
    def get_server_config(server_id):
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404
        try:
            if os.path.exists(server['config_path']):
                with open(server['config_path'], 'r') as f:
                    config_content = f.read()
                return jsonify({
                    "server_id": server_id,
                    "server_name": server['name'],
                    "config_path": server['config_path'],
                    "config_content": config_content,
                    "interface": server['interface'],
                    "public_key": server['server_public_key']
                })
            else:
                return jsonify({"error": "Config file not found"}), 404
        except Exception as e:
            return jsonify({"error": f"Failed to read config: {str(e)}"}), 500

    @app.route('/api/servers/<server_id>/config/download')
    def download_server_config(server_id):
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404
        try:
            if os.path.exists(server['config_path']):
                return send_file(server['config_path'], as_attachment=True, download_name=f"{server['interface']}.conf")
            else:
                return jsonify({"error": "Config file not found"}), 404
        except Exception as e:
            return jsonify({"error": f"Failed to download config: {str(e)}"}), 500

    @app.route('/api/servers/<server_id>/info')
    def get_server_info(server_id):
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404

        current_status = amnezia_manager.get_server_status(server_id)
        server['current_status'] = current_status
        config_preview = ""
        if os.path.exists(server['config_path']):
            try:
                with open(server['config_path'], 'r') as f:
                    lines = f.readlines()
                    config_preview = ''.join(lines[:min(10, len(lines))])
            except:
                config_preview = "Unable to read config file"

        server_info = {
            "id": server['id'],
            "name": server['name'],
            "protocol": server['protocol'],
            "port": server['port'],
            "status": current_status,
            "interface": server['interface'],
            "config_path": server['config_path'],
            "public_ip": server['public_ip'],
            "server_ip": server['server_ip'],
            "subnet": server['subnet'],
            "mtu": server.get('mtu', 1420),
            "obfuscation_enabled": server['obfuscation_enabled'],
            "obfuscation_params": server.get('obfuscation_params', {}),
            "clients_count": len(server['clients']),
            "created_at": server['created_at'],
            "config_preview": config_preview,
            "public_key": server['server_public_key'],
            "dns": server['dns'],
            "default_i_settings": {"i1": config.DEFAULT_I1, "i2": config.DEFAULT_I2, "i3": config.DEFAULT_I3, "i4": config.DEFAULT_I4, "i5": config.DEFAULT_I5}
        }
        return jsonify(server_info)

    @app.route('/api/default-i-settings', methods=['GET'])
    def get_default_i_settings():
        return jsonify({"i1": config.DEFAULT_I1, "i2": config.DEFAULT_I2, "i3": config.DEFAULT_I3, "i4": config.DEFAULT_I4, "i5": config.DEFAULT_I5})

    @app.route('/api/servers', methods=['GET'])
    def get_servers():
        for server in amnezia_manager.config["servers"]:
            server["status"] = amnezia_manager.get_server_status(server["id"])
            if 'mtu' not in server:
                server['mtu'] = 1420
        amnezia_manager.save_config()
        return jsonify(amnezia_manager.config["servers"])

    @app.route('/api/system/iptables-test')
    def iptables_test():
        server_id = request.args.get('server_id')
        if not server_id:
            return jsonify({"error": "server_id parameter required"}), 400
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404
        try:
            check_commands = [
                f"iptables -L INPUT -n | grep {server['interface']}",
                f"iptables -L FORWARD -n | grep {server['interface']}",
                f"iptables -t nat -L POSTROUTING -n | grep {server['subnet']}"
            ]
            results = {}
            for cmd in check_commands:
                try:
                    result = amnezia_manager.execute_command(cmd)
                    results[cmd] = "Found" if result else "Not found"
                except:
                    results[cmd] = "Error"
            return jsonify({
                "server_id": server_id, "server_name": server['name'],
                "interface": server['interface'], "subnet": server['subnet'],
                "iptables_check": results
            })
        except Exception as e:
            return jsonify({"error": f"iptables test failed: {str(e)}"}), 500
        
    @app.route('/api/servers/<server_id>/clients/<client_id>/config-both')
    def get_client_config_both(server_id, client_id):
        client = amnezia_manager.config["clients"].get(client_id)
        if not client or client.get("server_id") != server_id:
            return jsonify({"error": "Client not found"}), 404
        server = next((s for s in amnezia_manager.config['servers'] if s['id'] == server_id), None)
        if not server:
            return jsonify({"error": "Server not found"}), 404

        clean_config = amnezia_manager.generate_wireguard_client_config(server, client, include_comments=False)
        full_config = amnezia_manager.generate_wireguard_client_config(server, client, include_comments=True)
        return jsonify({
            "server_id": server_id, "client_id": client_id, "client_name": client['name'],
            "clean_config": clean_config, "full_config": full_config,
            "clean_length": len(clean_config), "full_length": len(full_config)
        })
        
    @app.route('/api/servers/<server_id>/clients/<client_id>/suspend', methods=['POST'])
    def suspend_client(server_id, client_id):
        success, message = amnezia_manager.suspend_client(server_id, client_id)
        if success:
            return jsonify({"status": "suspended", "client_id": client_id, "message": message})
        return jsonify({"error": message}), 404

    @app.route('/api/servers/<server_id>/clients/<client_id>/activate', methods=['POST'])
    def activate_client(server_id, client_id):
        success, message = amnezia_manager.activate_client(server_id, client_id)
        if success:
            return jsonify({"status": "activated", "client_id": client_id, "message": message})
        return jsonify({"error": message}), 404
        
    @app.route('/api/servers/<server_id>/traffic')
    def get_server_traffic(server_id):
        traffic = amnezia_manager.get_traffic_for_server(server_id)
        if traffic is None:
            return jsonify({"error": "Server not found or no traffic data"}), 404
        return jsonify(traffic)

    @app.route('/status')
    def get_container_uptime():
        result = subprocess.check_output(["stat", "-c %Y", "/proc/1/cmdline"], text=True)
        uptime_seconds_epoch = int(result.strip())
        now_epoch = int(time.time())
        uptime_seconds = now_epoch - uptime_seconds_epoch
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        return f"Container Uptime: {days}d {hours}h {minutes}m {seconds}s"

    @socketio.on('connect')
    def handle_connect():
        print(f"WebSocket connected from {request.remote_addr}")
        socketio.emit('status', {
            'message': 'Connected to AmneziaWG Web UI',
            'public_ip': amnezia_manager.public_ip,
            'nginx_port': config.NGINX_PORT,
            'server_port': request.environ.get('SERVER_PORT', 'unknown'),
            'client_port': request.environ.get('HTTP_X_FORWARDED_PORT', 'unknown')
        })
        all_traffic = {}
        for server in amnezia_manager.config['servers']:
            server_id = server['id']
            traffic = amnezia_manager.get_traffic_for_server(server_id)
            if traffic:
                all_traffic[server_id] = traffic
        if all_traffic:
            socketio.emit('traffic_update', {
                'timestamp': time.time(),
                'traffic': all_traffic
            })

    @socketio.on('disconnect')
    def handle_disconnect():
        print(f"WebSocket disconnected from {request.remote_addr}")