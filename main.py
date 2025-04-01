# main.py (Integrating Discovery)
import kivy
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock # Kivy's clock for scheduling on main thread
import asyncio
import logging # Use logging

# Import the discoverer - adjust path if needed
from networking.discovery import PeerDiscoverer

kivy.require('2.1.0') # Or your Kivy version

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
MY_USERNAME = "User" # Replace with dynamic setting later
MY_TCP_PORT = 50001 # Port for incoming P2P chat connections (must be unique per instance if on same machine)
# ---

class MainLayout(BoxLayout):
    # We'll add methods here later to interact with UI elements
    def update_status(self, text):
        if self.ids.status_label: # Check if the label exists in kv ids
             self.ids.status_label.text = f"Status: {text}"

    def update_user_list_ui(self, peers_list):
         # TODO: Implement actual UI update for the user list (e.g., RecycleView)
         logging.info(f"[UI Placeholder] Peers updated: {peers_list}")
         print(f"[UI Placeholder] Peers updated: {peers_list}") # Temporary print


class LANChatApp(App):
    discoverer = None
    p2p_server_task = None # For TCP server later

    def build(self):
        self.main_layout = MainLayout() # Keep a reference to the root layout
        return self.main_layout

    async def app_func(self):
        """This is the async version of the Kivy app lifecycle."""
        # Kivy automatically calls build() or loads KV first.
        # We just need to ensure our async logic runs after that.

        # --- Important: Run other async tasks ---
        # We need to start other tasks like discovery *concurrently*
        # with the Kivy event loop, which is implicitly running.

        logging.info("App started, initializing networking...")

        # Ensure the main_layout is available (set in build method)
        if not hasattr(self, 'main_layout') or not self.main_layout:
                logging.error("Main layout not available after build!")
                # Optionally, try calling build here, but it should have run.
                # self.main_layout = self.build() # build should return the layout
                # if not self.main_layout: # Still fails?
                #     return
                # For safety, let's re-build if missing, though it indicates a setup issue
                logging.warning("Attempting to re-build layout...")
                self.main_layout = self.build()
                if not self.main_layout:
                    logging.error("Failed to get layout on re-build.")
                    return # Cannot proceed

        # Use Clock.schedule_once to ensure UI updates happen on the main Kivy thread
        def safe_update_peer_list(peers_list):
                Clock.schedule_once(lambda dt: self.main_layout.update_user_list_ui(peers_list))

        def safe_update_status(text):
                Clock.schedule_once(lambda dt: self.main_layout.update_status(text))

        self.discoverer = PeerDiscoverer(
            username=MY_USERNAME,
            tcp_port=MY_TCP_PORT,
            peer_update_callback=safe_update_peer_list
        )

        # Start discovery listener and periodic broadcasts/cleanup
        # Running these as background tasks managed by asyncio
        # Start discoverer first
        discovery_start_task = asyncio.create_task(self.discoverer.start())

        # TODO: Start P2P TCP Server here later (Step 5)
        # self.p2p_server_task = asyncio.create_task(start_p2p_server(...))

        # Wait briefly for discovery to potentially start up before setting status
        await asyncio.sleep(0.1)
        safe_update_status(f"Online as {MY_USERNAME} ({self.discoverer.my_ip}:{MY_TCP_PORT})")

        # Keep this app_func running so background tasks continue
        # Wait for the discovery start task or other essential startup tasks if needed
        await discovery_start_task # Optional: wait if startup is critical before proceeding

        # Keep the app alive - Kivy's loop runs alongside asyncio tasks
        # We can await something that never completes, or just let the function exit
        # while background tasks created with create_task continue.
        # Let's use a long sleep as a placeholder way to keep app_func alive
        # if we needed to await other things later.
        try:
            while True:
                await asyncio.sleep(3600) # Sleep indefinitely basically
        except asyncio.CancelledError:
                logging.info("app_func task cancelled.")
        finally:
                logging.info("app_func exiting.")
                # Cleanup is handled in on_stop

    def on_stop(self):
        """Called when the Kivy app is stopping."""
        logging.info("Application stopping...")
        if self.discoverer:
            self.discoverer.stop()
        if self.p2p_server_task:
            self.p2p_server_task.cancel()
        logging.info("Cleanup complete.")
        # Allow asyncio loop to finish cleanup tasks
        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(asyncio.sleep(0.1)) # Short sleep to allow tasks to finish canceling


if __name__ == '__main__':
    # Use Kivy's asyncio integration to run the app
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(LANChatApp().app_func())
    except KeyboardInterrupt:
        logging.info("Ctrl+C detected. Stopping application.")
    finally:
        # Cancel remaining tasks on KeyboardInterrupt or other loop stop
        tasks = asyncio.all_tasks(loop=loop)
        for task in tasks:
            task.cancel()
        # Wait for tasks to finish canceling
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()
        logging.info("Asyncio loop closed.")