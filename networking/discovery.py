# networking/discovery.py
import asyncio
import socket
import json
import time
import logging # Use logging for better debugging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BROADCAST_IP = '<broadcast>' # Special address for broadcasting on local interfaces
# Alternatively, use a specific subnet broadcast like '192.168.1.255' if needed,
# but '<broadcast>' is generally preferred for wider compatibility.
DISCOVERY_PORT = 50000 # Port for discovery packets (choose an unused one)
BROADCAST_INTERVAL = 10 # Seconds between sending discovery broadcasts
PEER_TIMEOUT = BROADCAST_INTERVAL * 3.5 # Time after which a peer is considered offline

class DiscoveryProtocol(asyncio.DatagramProtocol):
    """Handles receiving discovery datagrams."""
    def __init__(self, discoverer):
        self.discoverer = discoverer
        super().__init__()

    def datagram_received(self, data, addr):
        """Called by asyncio when a datagram is received."""
        ip, _port = addr # We only care about the sender's IP
        try:
            message_str = data.decode('utf-8')
            message = json.loads(message_str)
            # Basic validation
            if isinstance(message, dict) and 'username' in message and 'tcp_port' in message:
                # Avoid processing our own broadcasts
                my_ip = self.discoverer.my_ip
                if ip != my_ip:
                     # Use call_soon_threadsafe if updating Kivy UI from another thread
                     # For now, let's assume PeerDiscoverer handles thread safety or direct update
                    self.discoverer.process_incoming_packet(message, ip)
            else:
                logging.warning(f"Received invalid discovery packet from {ip}: {message_str}")
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logging.warning(f"Could not decode discovery packet from {ip}: {e}")
        except Exception as e:
            logging.error(f"Error processing packet from {ip}: {e}", exc_info=True)

    def error_received(self, exc):
        logging.error(f"UDP discovery listener error: {exc}")

    def connection_lost(self, exc):
        logging.warning("UDP discovery listener closed.")


class PeerDiscoverer:
    """Manages UDP broadcasting and listening for peer discovery."""
    def __init__(self, username, tcp_port, peer_update_callback):
        self.username = username
        self.tcp_port = tcp_port # The port our TCP server will listen on
        self.peer_update_callback = peer_update_callback # Function to call when peer list changes
        self.peers = {} # Dictionary: {ip: {'username': name, 'tcp_port': port, 'last_seen': timestamp}}
        self.my_ip = self._get_local_ip()
        self.transport = None
        self.protocol = None
        self._broadcast_task = None
        self._cleanup_task = None
        self.loop = asyncio.get_running_loop()

        logging.info(f"Initializing PeerDiscoverer for {username} on {self.my_ip}:{self.tcp_port}")

    def _get_local_ip(self):
        # Helper to find primary local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Doesn't have to be reachable
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1' # Fallback
        finally:
            s.close()
        return ip

    def create_discovery_message(self):
        """Creates the JSON payload for broadcast."""
        message = {
            'username': self.username,
            'tcp_port': self.tcp_port,
            # Add other info if needed, e.g., version
        }
        return json.dumps(message).encode('utf-8')

    def process_incoming_packet(self, message, ip):
        """Updates peer list based on received packet."""
        now = time.time()
        peer_key = ip # Use IP as the unique key for a peer
        username = message['username']
        tcp_port = message['tcp_port']

        if peer_key not in self.peers or \
           self.peers[peer_key]['username'] != username or \
           self.peers[peer_key]['tcp_port'] != tcp_port:
            logging.info(f"Discovered/Updated peer: {username} at {ip}:{tcp_port}")
            self.peers[peer_key] = {'username': username, 'tcp_port': tcp_port, 'last_seen': now}
            self.peer_update_callback(self.get_peers_list()) # Notify main app
        else:
            # Just update last_seen timestamp
            self.peers[peer_key]['last_seen'] = now
            # Optional: Can trigger callback even on timestamp update if needed

    async def start_listening(self):
        """Starts the UDP listener."""
        logging.info(f"Starting discovery listener on port {DISCOVERY_PORT}")
        try:
            self.transport, self.protocol = await self.loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(self),
                local_addr=('0.0.0.0', DISCOVERY_PORT),
                allow_broadcast=True, # Important for receiving broadcasts
                reuse_port=True # Allows multiple instances on same machine (use with caution)
            )
            logging.info("Discovery listener started successfully.")
        except OSError as e:
             logging.error(f"Could not bind discovery listener to port {DISCOVERY_PORT}: {e}. Another app might be using it.")
             # Handle error appropriately (e.g., exit or notify user)
             self.transport = None # Ensure transport is None if failed
        except Exception as e:
            logging.error(f"Unexpected error starting listener: {e}", exc_info=True)
            self.transport = None


    async def _broadcast_periodically(self):
        """Sends broadcast packets at regular intervals."""
        # Create broadcast socket each time to potentially handle network changes
        # Or create once and reuse if preferred
        message_bytes = self.create_discovery_message()

        while True:
             # Create socket inside loop for robustness? Or outside for efficiency? Let's try outside.
            broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # SO_REUSEADDR might be needed depending on OS and exact setup
            # broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                logging.debug(f"Broadcasting presence: {message_bytes.decode()}")
                broadcast_sock.sendto(message_bytes, (BROADCAST_IP, DISCOVERY_PORT))
            except Exception as e:
                logging.error(f"Error broadcasting discovery message: {e}")
            finally:
                broadcast_sock.close() # Close socket after sending

            await asyncio.sleep(BROADCAST_INTERVAL)


    async def _cleanup_peers_periodically(self):
        """Removes peers that haven't been heard from."""
        while True:
            await asyncio.sleep(PEER_TIMEOUT / 2) # Check reasonably often
            now = time.time()
            removed_peer = False
            peers_to_remove = [ip for ip, data in self.peers.items() if now - data['last_seen'] > PEER_TIMEOUT]

            for ip in peers_to_remove:
                logging.info(f"Peer timed out: {self.peers[ip]['username']} at {ip}")
                del self.peers[ip]
                removed_peer = True

            if removed_peer:
                self.peer_update_callback(self.get_peers_list()) # Notify main app


    async def start(self):
        """Starts listening and broadcasting."""
        await self.start_listening()
        if self.transport: # Only start broadcasting if listening started successfully
            self._broadcast_task = asyncio.create_task(self._broadcast_periodically())
            self._cleanup_task = asyncio.create_task(self._cleanup_peers_periodically())
            logging.info("Discovery broadcasting and cleanup started.")
        else:
            logging.error("Cannot start broadcasting/cleanup as listener failed to start.")


    def get_peers_list(self):
        """Returns the current list of peers (excluding self)."""
        # Return a list of dictionaries for easier consumption by UI
        now = time.time()
        # Filter out timed-out peers just in case cleanup hasn't run yet
        active_peers = [
            {'ip': ip, 'username': data['username'], 'tcp_port': data['tcp_port']}
            for ip, data in self.peers.items()
            if now - data['last_seen'] <= PEER_TIMEOUT
        ]
        return active_peers


    def stop(self):
        """Stops broadcasting, listening, and cleanup tasks."""
        logging.info("Stopping discovery...")
        if self._broadcast_task:
            self._broadcast_task.cancel()
            self._broadcast_task = None
        if self._cleanup_task:
            self._cleanup_task.cancel()
            self._cleanup_task = None
        if self.transport:
            self.transport.close()
            self.transport = None
        logging.info("Discovery stopped.")