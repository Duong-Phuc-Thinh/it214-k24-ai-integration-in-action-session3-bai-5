import os
import sys
import json
import time
import random
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- CONFIGURATIONS & CONSTANTS ---
CONFIG_DIR = "config_repo"
CONFIG_PORT = 8888
EUREKA_PORT = 8761

SERVICES_METADATA = {
    "car-service": {
        "configs": {
            "spring.datasource.url": "jdbc:mysql://localhost:3306/autorent_car_dev",
            "car.pricing.weekend-multiplier": "1.35",
            "car.sync.interval-seconds": "60"
        }
    },
    "booking-service": {
        "configs": {
            "spring.datasource.url": "jdbc:mysql://localhost:3306/autorent_booking_dev",
            "booking.max-days-allowed": "30",
            "booking.discount.member-rate": "0.10"
        }
    },
    "payment-service": {
        "configs": {
            "payment.gateway.url": "https://api.sandbox.vnpay.vn/payment",
            "payment.timeout-ms": "5000",
            "payment.enable-sandbox": "true"
        }
    },
    "notification-service": {
        "configs": {
            "notification.email.sender": "noreply@autorent.com",
            "notification.retry.max-attempts": "3",
            "notification.template.booking-success": "Dear {name}, your booking {id} is confirmed!"
        }
    }
}

# Print with colors for better logging
def log(service, message, level="INFO"):
    colors = {
        "SYS": "\033[95m",     # Purple
        "CONFIG": "\033[96m",  # Cyan
        "EUREKA": "\033[93m",  # Yellow
        "CAR": "\033[92m",     # Green
        "BOOKING": "\033[94m", # Blue
        "PAYMENT": "\033[35m", # Magenta
        "NOTIF": "\033[36m",   # Light Cyan
    }
    reset = "\033[0m"
    color = colors.get(service.split("-")[0].upper()[:7], "\033[97m")
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{color}[{timestamp}] [{service}] [{level}] {message}{reset}")

# --- INITIALIZE MOCK CONFIG GIT REPOSITORY ---
def init_config_repo():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    for service_name, metadata in SERVICES_METADATA.items():
        filepath = os.path.join(CONFIG_DIR, f"{service_name}-dev.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(metadata["configs"], f, indent=4, ensure_ascii=False)
    log("SYSTEM", f"Initialized mock Git Repository at '{CONFIG_DIR}/'", "SYS")

# --- MOCK CONFIG SERVER ---
class ConfigServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress default logging

    def do_GET(self):
        # Schema: /<service-name>/<profile>
        parts = self.path.strip("/").split("/")
        if len(parts) >= 2:
            service, profile = parts[0], parts[1]
            filename = f"{service}-{profile}.json"
            filepath = os.path.join(CONFIG_DIR, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                    response = {
                        "name": service,
                        "profiles": [profile],
                        "propertySources": [
                            {
                                "name": f"file://{CONFIG_DIR}/{filename}",
                                "source": config_data
                            }
                        ]
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(response, indent=2).encode('utf-8'))
                    log("CONFIG-SERVER", f"Served configuration for {service}-{profile}", "OK")
                    return
                except Exception as e:
                    self.send_error(500, f"Error reading file: {str(e)}")
                    return
        self.send_error(404, "Config File Not Found")

def start_config_server():
    server = HTTPServer(('localhost', CONFIG_PORT), ConfigServerHandler)
    log("CONFIG-SERVER", f"Server started at http://localhost:{CONFIG_PORT}", "SYS")
    server.serve_forever()

# --- MOCK EUREKA SERVER ---
class EurekaRegistry:
    def __init__(self):
        self.apps = {} # format: { app_name: { instance_id: {host, port, status, last_heartbeat} } }
        self.lock = threading.Lock()

    def register(self, app_name, instance_id, host, port, status):
        with self.lock:
            if app_name not in self.apps:
                self.apps[app_name] = {}
            self.apps[app_name][instance_id] = {
                "host": host,
                "port": port,
                "status": status,
                "last_heartbeat": time.time()
            }

    def heartbeat(self, app_name, instance_id):
        with self.lock:
            if app_name in self.apps and instance_id in self.apps[app_name]:
                self.apps[app_name][instance_id]["last_heartbeat"] = time.time()
                return True
            return False

    def get_all(self):
        with self.lock:
            # Clean up instances older than 10 seconds (eviction)
            now = time.time()
            for app_name in list(self.apps.keys()):
                for inst_id in list(self.apps[app_name].keys()):
                    if now - self.apps[app_name][inst_id]["last_heartbeat"] > 10:
                        del self.apps[app_name][inst_id]
                        log("EUREKA-SERVER", f"Evicted expired instance {inst_id} from {app_name}", "WARN")
                if not self.apps[app_name]:
                    del self.apps[app_name]
            return self.apps

eureka_registry = EurekaRegistry()

class EurekaServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        # POST /eureka/v2/apps/<app_name>
        parts = self.path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "eureka" and parts[1] == "v2" and parts[2] == "apps":
            app_name = parts[3].lower()
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            
            instance_id = post_data.get("instanceId")
            port = post_data.get("port")
            host = post_data.get("host", "localhost")
            status = post_data.get("status", "UP")
            
            eureka_registry.register(app_name, instance_id, host, port, status)
            log("EUREKA-SERVER", f"Registered {app_name.upper()} (Instance: {instance_id} at {host}:{port})", "REG")
            self.send_response(201)
            self.end_headers()
            return
        self.send_error(400, "Invalid request path or body")

    def do_PUT(self):
        # PUT /eureka/v2/apps/<app_name>/<instance_id>
        parts = self.path.strip("/").split("/")
        if len(parts) >= 5 and parts[0] == "eureka" and parts[1] == "v2" and parts[2] == "apps":
            app_name = parts[3].lower()
            instance_id = parts[4]
            success = eureka_registry.heartbeat(app_name, instance_id)
            if success:
                self.send_response(200)
                self.end_headers()
            else:
                self.send_error(404, "Instance not found")
            return
        self.send_error(400, "Invalid path")

    def do_GET(self):
        # GET /eureka/v2/apps
        if self.path == "/eureka/v2/apps":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(eureka_registry.get_all(), indent=2).encode('utf-8'))
            return
        self.send_error(404)

def start_eureka_server():
    server = HTTPServer(('localhost', EUREKA_PORT), EurekaServerHandler)
    log("EUREKA-SERVER", f"Server started at http://localhost:{EUREKA_PORT}", "SYS")
    server.serve_forever()

# --- MICROSERVICE EMULATOR --- 
class MicroserviceEmulator:
    def __init__(self, name, profile="dev"):
        self.name = name
        self.profile = profile
        self.port = random.randint(10000, 20000)
        self.instance_id = f"{self.name}-instance-{self.port}"
        self.configs = {}
        self.running = True

    def fetch_config(self):
        url = f"http://localhost:{CONFIG_PORT}/{self.name}/{self.profile}"
        log(self.name, f"Fetching configuration from Config Server... ({url})", "CONFIG")
        try:
            req = Request(url)
            with urlopen(req) as res:
                data = json.loads(res.read().decode('utf-8'))
                self.configs = data["propertySources"][0]["source"]
                log(self.name, f"Successfully loaded configs: {self.configs}", "CONFIG_OK")
        except URLError as e:
            log(self.name, f"Failed to fetch configs: {e}. Defaulting to empty config.", "ERROR")
            self.configs = {}

    def register_to_eureka(self):
        url = f"http://localhost:{EUREKA_PORT}/eureka/v2/apps/{self.name}"
        payload = {
            "instanceId": self.instance_id,
            "host": "localhost",
            "port": self.port,
            "status": "UP"
        }
        try:
            req = Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urlopen(req) as res:
                if res.status in (200, 201):
                    log(self.name, f"Successfully registered on Eureka with port {self.port}", "EUREKA_OK")
        except URLError as e:
            log(self.name, f"Failed to register on Eureka: {e}", "ERROR")

    def send_heartbeat(self):
        url = f"http://localhost:{EUREKA_PORT}/eureka/v2/apps/{self.name}/{self.instance_id}"
        try:
            req = Request(url, method='PUT')
            with urlopen(req) as res:
                if res.status == 200:
                    pass # Heartbeat silent confirmation to keep console clean
        except URLError as e:
            log(self.name, f"Heartbeat failed: {e}", "ERROR")

    def discover_service(self, target_service_name):
        url = f"http://localhost:{EUREKA_PORT}/eureka/v2/apps"
        try:
            req = Request(url)
            with urlopen(req) as res:
                registry = json.loads(res.read().decode('utf-8'))
                instances = registry.get(target_service_name, {})
                if instances:
                    inst_list = list(instances.values())
                    # Load balance using random choice
                    selected = random.choice(inst_list)
                    return selected
        except Exception as e:
            log(self.name, f"Discovery error: {e}", "ERROR")
        return None

    def run(self):
        # 1. Fetch Config
        self.fetch_config()
        time.sleep(1)
        
        # 2. Register to Eureka
        self.register_to_eureka()
        
        # 3. Main Loop: Send heartbeats & simulate transaction traffic
        heartbeat_counter = 0
        while self.running:
            time.sleep(1)
            heartbeat_counter += 1
            
            # Send heartbeat every 3 seconds
            if heartbeat_counter % 3 == 0:
                self.send_heartbeat()
            
            # Simulation flow for booking-service (demonstrating discovery and call flow)
            if self.name == "booking-service" and random.random() < 0.2: # 20% chance of trigger per sec
                log(self.name, "Initiating a self-drive car rental booking...", "BIZ")
                
                # Discover car-service
                car_inst = self.discover_service("car-service")
                if car_inst:
                    log(self.name, f"[Discovery] Found 'car-service' at {car_inst['host']}:{car_inst['port']}", "DISCOVERY")
                    log(self.name, f"Checking car availability with weekend multiplier multiplier: {self.configs.get('booking.discount.member-rate', '0.10')} member discount applied.", "RPC")
                else:
                    log(self.name, "[Discovery Failed] 'car-service' is currently offline! Cannot lease car.", "WARN")
                    continue

                # Discover payment-service
                pay_inst = self.discover_service("payment-service")
                if pay_inst:
                    log(self.name, f"[Discovery] Found 'payment-service' at {pay_inst['host']}:{pay_inst['port']}", "DISCOVERY")
                    log(self.name, "Processing payment securely...", "RPC")
                else:
                    log(self.name, "[Discovery Failed] 'payment-service' offline!", "WARN")
                    continue

                # Discover notification-service
                notif_inst = self.discover_service("notification-service")
                if notif_inst:
                     log(self.name, f"[Discovery] Found 'notification-service' at {notif_inst['host']}:{notif_inst['port']}", "DISCOVERY")
                     log(self.name, "Triggered success emails & booking notifications successfully!", "RPC")
                else:
                    log(self.name, "[Discovery Failed] 'notification-service' offline!", "WARN")

    def stop(self):
        self.running = False

# --- RUNNER MANAGEMENT ---
def main():
    print("===============================================================")
    print("    AUTORENT SPRING CLOUD & SERVICE DISCOVERY EMULATOR         ")
    print("===============================================================")

    # Step 1: Initialize Git Local Config Directory
    init_config_repo()
    
    # Step 2: Boot Servers
    threads = []
    config_thread = threading.Thread(target=start_config_server, daemon=True)
    config_thread.start()
    threads.append(config_thread)
    
    eureka_thread = threading.Thread(target=start_eureka_server, daemon=True)
    eureka_thread.start()
    threads.append(eureka_thread)
    
    # Let servers boot
    time.sleep(2)
    
    # Step 3: Boot Client Microservices
    services_to_start = [
        "car-service", 
        "booking-service", 
        "payment-service", 
        "notification-service"
    ]
    
    service_instances = []
    for s_name in services_to_start:
        emulator = MicroserviceEmulator(s_name)
        inst_thread = threading.Thread(target=emulator.run, daemon=True)
        inst_thread.start()
        service_instances.append(emulator)
        time.sleep(0.5) # staggered startup

    # Also, simulate scaling by adding an extra instance of car-service
    time.sleep(1)
    log("SYSTEM", "Scaling up 'car-service' - starting instance #2 for high availability...", "SYS")
    car_instance_2 = MicroserviceEmulator("car-service")
    inst_thread_2 = threading.Thread(target=car_instance_2.run, daemon=True)
    inst_thread_2.start()
    service_instances.append(car_instance_2)

    # Monitor for exit
    log("SYSTEM", "Infrastructure is active. Press Ctrl+C to stop simulation.", "SYS")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping infrastructure & client simulations...")
        for inst in service_instances:
            inst.stop()
        sys.exit(0)

if __name__ == "__main__":
    main()
