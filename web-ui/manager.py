import os
import json
import subprocess
import uuid
import base64
import random
import requests
import threading
import time
import ipaddress
import config

class AmneziaManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self.config = self.load_config()
        self.ensure_directories()
        self.public_ip = self.detect_public_ip()
        self.traffic_update_interval = 5

        if config.AUTO_START_SERVERS:
            self.auto_start_servers()
            
        self.start_traffic_updates()

    def ensure_directories(self):
        os.makedirs(config.CONFIG_DIR, exist_ok=True)
        os.makedirs(config.WIREGUARD_CONFIG_DIR, exist_ok=True)
        os.makedirs('/var/log/amnezia', exist_ok=True)

    def detect_public_ip(self):
        try:
            services = ['http://ifconfig.me', 'https://api.ipify.org', 'https://ident.me']
            for service in services:
                try:
                    response = requests.get(service, timeout=5)
                    if response.status_code == 200:
                        ip = response.text.strip()
                        if self.is_valid_ip(ip):
                            print(f"Detected public IP: {ip}")
                            return ip
                except:
                    continue
            try:
                result = self.execute_command("ip route get 1 | awk '{print $7}' | head -1")
                if result and self.is_valid_ip(result):
                    print(f"Detected local IP: {result}")
                    return result
            except:
                pass
        except Exception as e:
            print(f"Failed to detect public IP: {e}")
        return "YOUR_SERVER_IP"

    def is_valid_ip(self, ip):
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            for part in parts:
                if not 0 <= int(part) <= 255:
                    return False
            return True
        except:
            return False

    def auto_start_servers(self):
        print("Checking for existing servers to auto-start...")
        for server in self.config["servers"]:
            if os.path.exists(server['config_path']):
                current_status = self.get_server_status(server['id'])
                if current_status == 'stopped' and server.get('auto_start', True):
                    print(f"Auto-starting server: {server['name']}")
                    self.start_server(server['id'])

    def load_config(self):
        if os.path.exists(config.CONFIG_FILE):
            with open(config.CONFIG_FILE, 'r') as f:
                return json.load(f)
        return {"servers": [], "clients": {}}

    def save_config(self):
        with open(config.CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)

    def execute_command(self, command):
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Command failed: {e}")
            return None

    def generate_wireguard_keys(self):
        try:
            private_key = self.execute_command("wg genkey")
            if private_key:
                public_key = self.execute_command(f"echo '{private_key}' | wg pubkey")
                return {"private_key": private_key, "public_key": public_key}
        except Exception as e:
            print(f"Key generation failed: {e}")
        fake_private = base64.b64encode(os.urandom(32)).decode('utf-8')
        fake_public = base64.b64encode(os.urandom(32)).decode('utf-8')
        return {"private_key": fake_private, "public_key": fake_public}

    def generate_preshared_key(self):
        try:
            return self.execute_command("wg genpsk")
        except:
            return base64.b64encode(os.urandom(32)).decode('utf-8')

    def generate_obfuscation_params(self, mtu=1420):
        S1 = random.randint(15, min(150, mtu - 148))
        s2_candidates = [s for s in range(15, min(150, mtu - 92) + 1) if s != S1 + 56]
        S2 = random.choice(s2_candidates)
        Jmin = random.randint(4, mtu - 2)
        return {
            "Jc": random.randint(4, 12),
            "Jmin": Jmin,
            "Jmax": random.randint(Jmin + 1, mtu),
            "S1": S1,
            "S2": S2,
            "S3": random.randint(1, 256),
            "S4": random.randint(1, 32),
            "H1": random.randint(10000, 100000),
            "H2": random.randint(100000, 200000),
            "H3": random.randint(200000, 300000),
            "H4": random.randint(300000, 400000),
            "MTU": mtu
        }

    def create_wireguard_server(self, server_data):
        server_name = server_data.get('name', 'New Server')
        port = server_data.get('port', config.DEFAULT_PORT)
        subnet = server_data.get('subnet', config.DEFAULT_SUBNET)
        mtu = server_data.get('mtu', config.DEFAULT_MTU)

        custom_dns = server_data.get('dns')
        if custom_dns:
            if isinstance(custom_dns, str):
                dns_servers = [dns.strip() for dns in custom_dns.split(',') if dns.strip()]
            elif isinstance(custom_dns, list):
                dns_servers = custom_dns
            else:
                dns_servers = config.DNS_SERVERS
        else:
            dns_servers = config.DNS_SERVERS

        if mtu < 1280 or mtu > 1440:
            raise ValueError(f"MTU must be between 1280 and 1440, got {mtu}")

        for dns in dns_servers:
            if not self.is_valid_ip(dns):
                raise ValueError(f"Invalid DNS server IP: {dns}")

        enable_obfuscation = server_data.get('obfuscation', config.ENABLE_OBFUSCATION)
        auto_start = server_data.get('auto_start', config.AUTO_START_SERVERS)
        server_id = str(uuid.uuid4())[:6]
        interface_name = f"wg-{server_id}"
        config_path = os.path.join(config.WIREGUARD_CONFIG_DIR, f"{interface_name}.conf")
        server_keys = self.generate_wireguard_keys()

        obfuscation_params = None
        if enable_obfuscation:
            obfuscation_params = server_data.get('obfuscation_params', self.generate_obfuscation_params(mtu))
                
        awg2_enabled = server_data.get('awg2', False)
        subnet_parts = subnet.split('/')
        network = subnet_parts[0]
        prefix = subnet_parts[1] if len(subnet_parts) > 1 else "24"
        server_ip = self.get_server_ip(network)

        server_config_content = f"""[Interface]
PrivateKey = {server_keys['private_key']}
Address = {server_ip}/{prefix}
ListenPort = {port}
SaveConfig = false
MTU = {mtu}
"""
        if enable_obfuscation and obfuscation_params:
            server_config_content += f"""Jc = {obfuscation_params['Jc']}
Jmin = {obfuscation_params['Jmin']}
Jmax = {obfuscation_params['Jmax']}
S1 = {obfuscation_params['S1']}
S2 = {obfuscation_params['S2']}
"""
            if awg2_enabled:
                server_config_content += f"""S3 = {obfuscation_params['S3']}
S4 = {obfuscation_params['S4']}
"""
            server_config_content += f"""H1 = {obfuscation_params['H1']}
H2 = {obfuscation_params['H2']}
H3 = {obfuscation_params['H3']}
H4 = {obfuscation_params['H4']}
"""

        server_config = {
            "id": server_id,
            "name": server_name,
            "protocol": "wireguard",
            "port": port,
            "status": "stopped",
            "interface": interface_name,
            "config_path": config_path,
            "server_public_key": server_keys['public_key'],
            "server_private_key": server_keys['private_key'],
            "subnet": subnet,
            "server_ip": server_ip,
            "mtu": mtu,
            "public_ip": self.public_ip,
            "obfuscation_enabled": enable_obfuscation,
            "awg2_enabled": awg2_enabled,
            "obfuscation_params": obfuscation_params,
            "auto_start": auto_start,
            "dns": dns_servers,
            "clients": [],
            "unbound_nat_ips": [],
            "created_at": time.time()
        }

        with open(config_path, 'w') as f:
            f.write(server_config_content)

        self.config["servers"].append(server_config)
        self.save_config()

        if auto_start:
            print(f"Auto-starting new server: {server_name}")
            self.start_server(server_id)

        return server_config
    
    def apply_live_config(self, interface):
        try:
            command = f"bash -c 'awg syncconf {interface} <(awg-quick strip {interface})'"
            result = self.execute_command(command)
            if result is not None:
                print(f"Live config applied to {interface}")
                return True
            print(f"Failed to apply live config to {interface}")
            return False
        except Exception as e:
            print(f"Error applying live config to {interface}: {e}")
            return False

    def get_server_ip(self, network):
        parts = network.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.1"
        return "10.0.0.1"

    def get_new_client_ip(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False

        unbound_ips = server.get("unbound_nat_ips", [])
        if unbound_ips:
            unbound_ip = unbound_ips.pop(0)
            server["unbound_nat_ips"] = unbound_ips
            self.save_config()
            return unbound_ip

        subnet_str = server['subnet']
        network = ipaddress.ip_network(subnet_str)
    
        used_ips = {server['server_ip']}
        for client in server.get('clients', []):
            used_ips.add(client['client_ip'])

        for ip in network.hosts():
            ip_str = str(ip)
            if ip_str not in used_ips:
                return ip_str

        print(f"Subnet {subnet_str} is full! No available IPs.")
        return False

    def delete_server(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False

        if server['status'] == 'running':
            self.stop_server(server_id)

        if os.path.exists(server['config_path']):
            os.remove(server['config_path'])

        self.config["clients"] = {k: v for k, v in self.config["clients"].items()
                                if v.get("server_id") != server_id}
        self.config["servers"] = [s for s in self.config["servers"] if s["id"] != server_id]
        self.save_config()
        return True

    def add_wireguard_client(self, server_id, client_name, apply_i_settings=False, i_settings=None):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return None

        client_id = str(uuid.uuid4())[:6]
        client_keys = self.generate_wireguard_keys()
        preshared_key = self.generate_preshared_key()
        client_ip = self.get_new_client_ip(server_id)
        
        if not client_ip:
            return None

        client_i_settings = {}
        if apply_i_settings:
            client_i_settings = {'i1': config.DEFAULT_I1, 'i2': config.DEFAULT_I2, 'i3': config.DEFAULT_I3, 'i4': config.DEFAULT_I4, 'i5': config.DEFAULT_I5}
            if i_settings:
                for i in range(1, 6):
                    i_key = f'i{i}'
                    if i_key in i_settings and i_settings[i_key]:
                        client_i_settings[i_key] = i_settings[i_key]

        client_config = {
            "id": client_id,
            "name": client_name,
            "server_id": server_id,
            "server_name": server["name"],
            "status": "active",
            "created_at": time.time(),
            "client_private_key": client_keys["private_key"],
            "client_public_key": client_keys["public_key"],
            "preshared_key": preshared_key,
            "client_ip": client_ip,
            "obfuscation_enabled": server["obfuscation_enabled"],
            "obfuscation_params": server["obfuscation_params"],
            "apply_i_settings": apply_i_settings,
            "i_settings": client_i_settings,
            "awg2_enabled": server.get("awg2_enabled", False)
        }

        client_peer_config = f"""
# Client: {client_config['name']}
[Peer]
PublicKey = {client_keys['public_key']}
PresharedKey = {preshared_key}
AllowedIPs = {client_ip}/32
"""
        with open(server['config_path'], 'a') as f:
            f.write(client_peer_config)

        server["clients"].append(client_config)
        self.config["clients"][client_id] = client_config.copy()
        self.save_config()
        
        if server['status'] == 'running':
            self.apply_live_config(server['interface'])
            
        print(f"Client {client_config['name']} added")
        config_content = self.generate_wireguard_client_config(server, client_config, include_comments=True)
        return client_config, config_content

    def delete_client(self, server_id, client_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False

        client = next((c for c in server["clients"] if c["id"] == client_id), None)
        if not client:
            return False

        server["clients"] = [c for c in server["clients"] if c["id"] != client_id]
        if client_id in self.config["clients"]:
            del self.config["clients"][client_id]

        server.setdefault("unbound_nat_ips", []).append(client["client_ip"])
        self.rewrite_server_conf_without_client(server, client)
        self.save_config()

        if server['status'] == 'running':
            self.apply_live_config(server['interface'])
            
        print(f"Client {server['name']}:{client['name']} removed")
        return True
    
    def rewrite_server_conf_without_client(self, server, client):
        if not os.path.exists(server['config_path']):
            return

        with open(server['config_path'], 'r') as f:
            lines = f.readlines()

        new_lines = []
        skip = False
        client_marker = f"# Client: {client['name']}"

        for line in lines:
            stripped = line.strip()
            if stripped == client_marker:
                skip = True
                continue
            if skip and stripped.startswith("# Client:"):
                skip = False
            if skip:
                continue
            new_lines.append(line)

        while new_lines and new_lines[-1].strip() == '':
            new_lines.pop()

        with open(server['config_path'], 'w') as f:
            f.writelines(new_lines)

    def generate_wireguard_client_config(self, server, client_config, include_comments=True):
        config = ""
        if include_comments:
            config = f"""# AmneziaWG Client Configuration
# Server: {server['name']}
# Client: {client_config['name']}
# Generated: {time.ctime()}
# Server IP: {server['public_ip']}:{server['port']}
"""
        config += f"""[Interface]
PrivateKey = {client_config['client_private_key']}
Address = {client_config['client_ip']}/32
DNS = {', '.join(server['dns'])}
MTU = {server['mtu']}
"""
        if client_config.get('obfuscation_enabled', False) and client_config.get('obfuscation_params'):
            params = client_config['obfuscation_params']
            config += f"""Jc = {params['Jc']}
Jmin = {params['Jmin']}
Jmax = {params['Jmax']}
S1 = {params['S1']}
S2 = {params['S2']}
"""
        if client_config.get('awg2_enabled', False):
            config += f"""S3 = {params['S3']}
S4 = {params['S4']}
"""
        config += f"""H1 = {params['H1']}
H2 = {params['H2']}
H3 = {params['H3']}
H4 = {params['H4']}
"""
        if client_config.get('apply_i_settings', False):
            i_settings = client_config.get('i_settings', {})
            i1_value = i_settings.get('i1', '')
            if i1_value:
                for i in range(1, 6):
                    i_value = i_settings.get(f'i{i}', '')
                    if i_value:
                        config += f"I{i} = {i_value}\n"
        
        config += f"""
[Peer]
PublicKey = {server['server_public_key']}
PresharedKey = {client_config['preshared_key']}
Endpoint = {server['public_ip']}:{server['port']}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
        return config
    
    def update_client_i_settings(self, server_id, client_id, apply_i_settings=None, i_settings=None):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return None, "Server not found"

        client = next((c for c in server["clients"] if c["id"] == client_id), None)
        if not client:
            return None, "Client not found"
        
        if apply_i_settings is not None:
            client['apply_i_settings'] = apply_i_settings
            if client_id in self.config["clients"]:
                self.config["clients"][client_id]['apply_i_settings'] = apply_i_settings
        
        if i_settings is not None:
            new_i_settings = {}
            if apply_i_settings or client.get('apply_i_settings', False):
                new_i_settings = {'i1': config.DEFAULT_I1, 'i2': config.DEFAULT_I2, 'i3': config.DEFAULT_I3, 'i4': config.DEFAULT_I4, 'i5': config.DEFAULT_I5}
                for i in range(1, 6):
                    i_key = f'i{i}'
                    if i_key in i_settings and i_settings[i_key]:
                        new_i_settings[i_key] = i_settings[i_key]
                    elif client.get('i_settings', {}).get(i_key):
                        new_i_settings[i_key] = client['i_settings'][i_key]
            
            client['i_settings'] = new_i_settings
            if client_id in self.config["clients"]:
                self.config["clients"][client_id]['i_settings'] = new_i_settings.copy()
        
        self.save_config()
        config_content = self.generate_wireguard_client_config(server, client, include_comments=True)
        return client, config_content
    
    def suspend_client(self, server_id, client_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False, "Server not found"
        client = next((c for c in server["clients"] if c["id"] == client_id), None)
        if not client:
            return False, "Client not found"

        suspended_dir = os.path.join(config.WIREGUARD_CONFIG_DIR, 'suspended')
        os.makedirs(suspended_dir, exist_ok=True)

        if os.path.exists(server['config_path']):
            with open(server['config_path'], 'r') as f:
                content = f.read()

            client_marker = f"# Client: {client['name']}"
            lines = content.split('\n')
            
            peer_block = []
            in_peer_block = False
            for line in lines:
                if line.strip() == client_marker:
                    in_peer_block = True
                    peer_block.append(line)
                elif in_peer_block and line.strip().startswith('[Peer]'):
                    peer_block.append(line)
                elif in_peer_block and line.strip() and not line.strip().startswith('#'):
                    peer_block.append(line)
                elif in_peer_block and not line.strip():
                    peer_block.append(line)
                    break

            if peer_block:
                suspended_path = os.path.join(suspended_dir, f"{client_id}.conf")
                with open(suspended_path, 'w') as f:
                    f.write('\n'.join(peer_block))

        self.rewrite_server_conf_without_client(server, client)
        client['status'] = 'suspended'
        if client_id in self.config["clients"]:
            self.config["clients"][client_id]['status'] = 'suspended'
        self.save_config()

        if server['status'] == 'running':
            self.apply_live_config(server['interface'])
        return True, "Client suspended successfully"

    def activate_client(self, server_id, client_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False, "Server not found"
        client = next((c for c in server["clients"] if c["id"] == client_id), None)
        if not client:
            return False, "Client not found"
        if client.get('status') != 'suspended':
            return False, "Client is not suspended"

        suspended_path = os.path.join(config.WIREGUARD_CONFIG_DIR, 'suspended', f"{client_id}.conf")
        if not os.path.exists(suspended_path):
            return False, "Suspended config file not found"

        with open(suspended_path, 'r') as f:
            suspended_config = f.read()

        with open(server['config_path'], 'a') as f:
            f.write('\n' + suspended_config)
        os.remove(suspended_path)

        client['status'] = 'active'
        if client_id in self.config["clients"]:
            self.config["clients"][client_id]['status'] = 'active'
        self.save_config()

        if server['status'] == 'running':
            self.apply_live_config(server['interface'])
        return True, "Client activated successfully"

    def setup_iptables(self, interface, subnet):
        try:
            script_path = "/app/scripts/setup_iptables.sh"
            if os.path.exists(script_path):
                result = self.execute_command(f"{script_path} {interface} {subnet}")
                return result is not None
            return False
        except Exception as e:
            print(f"Error setting up iptables: {e}")
            return False

    def cleanup_iptables(self, interface, subnet):
        try:
            script_path = "/app/scripts/cleanup_iptables.sh"
            if os.path.exists(script_path):
                result = self.execute_command(f"{script_path} {interface} {subnet}")
                return result is not None
            return False
        except Exception as e:
            print(f"Error cleaning up iptables: {e}")
            return False

    def start_server(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False
        try:
            result = self.execute_command(f"/usr/bin/awg-quick up {server['interface']}")
            if result is not None:
                self.setup_iptables(server['interface'], server['subnet'])
                server['status'] = 'running'
                self.save_config()
                threading.Thread(target=self.simulate_server_operation, args=(server_id, 'running')).start()
                return True
        except Exception as e:
            print(f"Failed to start server {server_id}: {e}")
        return False

    def stop_server(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return False
        try:
            self.cleanup_iptables(server['interface'], server['subnet'])
            result = self.execute_command(f"/usr/bin/awg-quick down {server['interface']}")
            if result is not None:
                server['status'] = 'stopped'
                self.save_config()
                threading.Thread(target=self.simulate_server_operation, args=(server_id, 'stopped')).start()
                return True
        except Exception as e:
            print(f"Failed to stop server {server_id}: {e}")
        return False

    def get_server_status(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return "not_found"
        try:
            result = self.execute_command(f"ip link show {server['interface']} 2>/dev/null")
            if result and "state UNKNOWN" in result:
                return "running"
            return "stopped"
        except:
            return "stopped"

    def simulate_server_operation(self, server_id, status):
        time.sleep(2)
        self.socketio.emit('server_status', {
            'server_id': server_id,
            'status': status
        })

    def get_client_configs(self, server_id=None):
        if server_id:
            server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
            return server['clients'] if server else []
        else:
            clients = []
            for client_id, client in self.config["clients"].items():
                client_copy = client.copy()
                client_copy.setdefault('apply_i_settings', False)
                client_copy.setdefault('i_settings', {})
                client_copy.setdefault('status', 'active')
                clients.append(client_copy)
            return clients

    def get_traffic_for_server(self, server_id):
        server = next((s for s in self.config['servers'] if s['id'] == server_id), None)
        if not server:
            return None

        interface = server['interface']
        output = self.execute_command(f"/usr/bin/awg show {interface}")
        if not output:
            return None

        peer_data = {}
        lines = output.splitlines()
        current_peer = None
        for line in lines:
            line = line.strip()
            if line.startswith("peer:"):
                current_peer = line.split("peer:")[1].strip()
                peer_data[current_peer] = {"received": "0 B", "sent": "0 B", "last_handshake": "Never", "endpoint": "", "latest_handshake_epoch": 0}
            elif line.startswith("transfer:") and current_peer:
                parts = line[len("transfer:"):].strip().split(',')
                peer_data[current_peer]["received"] = parts[0].strip() if len(parts) > 0 else "0 B"
                peer_data[current_peer]["sent"] = parts[1].strip() if len(parts) > 1 else "0 B"
            elif line.startswith("endpoint:") and current_peer:
                peer_data[current_peer]["endpoint"] = line.split("endpoint:")[1].strip()
            elif line.startswith("allowed ips:") and current_peer:
                peer_data[current_peer]["allowed_ips"] = line.split("allowed ips:")[1].strip()
            elif line.startswith("latest handshake:") and current_peer:
                handshake_line = line[len("latest handshake:"):].strip()
                peer_data[current_peer]["last_handshake"] = handshake_line
                try:
                    if handshake_line != "Never":
                        import re
                        total_seconds = 0
                        parts = handshake_line.replace(' ago', '').split(', ')
                        for part in parts:
                            match = re.match(r'(\d+)\s+(\w+)', part)
                            if match:
                                value, unit = int(match.group(1)), match.group(2)
                                if unit.startswith('second'): total_seconds += value
                                elif unit.startswith('minute'): total_seconds += value * 60
                                elif unit.startswith('hour'): total_seconds += value * 3600
                                elif unit.startswith('day'): total_seconds += value * 86400
                        peer_data[current_peer]["latest_handshake_epoch"] = time.time() - total_seconds
                except:
                    pass

        clients_data = {}
        for client_id, client in self.config["clients"].items():
            if client.get("server_id") == server_id:
                pubkey = client.get("client_public_key")
                if pubkey in peer_data:
                    clients_data[client_id] = {
                        "received": peer_data[pubkey]["received"],
                        "sent": peer_data[pubkey]["sent"],
                        "last_handshake": peer_data[pubkey]["last_handshake"],
                        "endpoint": peer_data[pubkey]["endpoint"]
                    }
                else:
                    clients_data[client_id] = {"received": "0 B", "sent": "0 B", "last_handshake": "Never", "endpoint": ""}
        return clients_data
    
    def start_traffic_updates(self):
        def update_traffic():
            while True:
                try:
                    all_traffic = {}
                    for server in self.config['servers']:
                        server_id = server['id']
                        traffic = self.get_traffic_for_server(server_id)
                        if traffic:
                            all_traffic[server_id] = traffic
                    if all_traffic:
                        self.socketio.emit('traffic_update', {
                            'timestamp': time.time(),
                            'traffic': all_traffic
                        })
                except Exception as e:
                    print(f"Traffic update error: {e}")
                self.socketio.sleep(self.traffic_update_interval)
        
        self.socketio.start_background_task(update_traffic)