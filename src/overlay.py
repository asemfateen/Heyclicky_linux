#!/usr/bin/env python3
import os
import sys
import json
import math
import threading
import subprocess
import time
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import cairo

# Try to import GtkLayerShell for Wayland overlays
has_layer_shell = False
try:
    gi.require_version('GtkLayerShell', '0.1')
    from gi.repository import GtkLayerShell
    has_layer_shell = True
except (ValueError, ImportError):
    pass

STATE_FILE = f"/tmp/heyclicky_state_{os.getuid()}.json"

class HeyClickyOverlayWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        
        # Determine session type
        env_file = os.path.expanduser("~/.config/heyclicky/env.conf")
        session_type = "wayland"
        if os.path.exists(env_file):
            try:
                with open(env_file, "r") as f:
                    for line in f:
                        if "SESSION_TYPE" in line:
                            session_type = line.split("=")[-1].strip().strip('"').strip("'")
            except Exception:
                pass

        self.set_title("HeyClicky Overlay")
        self.set_decorated(False)
        
        # Configure global window flags to completely bypass focus and task managers
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)

        # Resolve active monitor from mouse cursor position
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        pointer = seat.get_pointer()
        screen, x, y = pointer.get_position()
        monitor = display.get_monitor_at_point(x, y)
        
        # Use Layer Shell on Wayland for non-GNOME environments (GNOME doesn't support layer shell protocol)
        self.using_layer_shell = False
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if has_layer_shell and session_type == "wayland" and "gnome" not in desktop and "kde" not in desktop:
            try:
                GtkLayerShell.init_for_window(self)
                GtkLayerShell.set_monitor(self, monitor)
                GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
                GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
                GtkLayerShell.set_exclusive_zone(self, -1)
                # Anchor to all sides to make it fullscreen
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
                self.using_layer_shell = True
                print(f"Layer Shell initialized for window overlay on monitor: {monitor}")
            except Exception as e:
                print(f"Failed to initialize GtkLayerShell: {e}. Falling back to standard GTK window.", file=sys.stderr)
                self.using_layer_shell = False

        if not self.using_layer_shell:
            self.fullscreen_on_monitor(screen, monitor)
            self.set_keep_above(True)

        # Support alpha channel (transparency)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Handle window signals
        self.connect("draw", self.on_draw)
        self.connect("destroy", Gtk.main_quit)

        # Tracking state and animation positions
        self.state = "idle"
        self.target_x = None
        self.target_y = None
        self.target_label = None
        self.current_monitor = None
        
        self.current_x = None
        self.current_y = None
        self.opacity = 0.0  # Fade animation
        self.response_text = ""
        self.last_state_change = time.time()
        self.state_timeout = {"processing": 30, "responding": 60}
        
        # Schedule configuration of click-through and polling loop once realized
        self.connect("realize", self.on_realize)
        
        # High frequency animation tick (60 FPS ~ 16ms)
        GLib.timeout_add(16, self.on_anim_tick)
        
        # Slightly slower state file polling tick (100ms)
        GLib.timeout_add(100, self.on_poll_state)

        # Start the global evdev hardware hotkey listener
        self.start_evdev_listener()

    def get_png_size(self, filepath):
        """Parses a PNG file header to get its width and height without loading the image."""
        try:
            import struct
            with open(filepath, 'rb') as f:
                data = f.read(24)
                if data[:8] == b'\x89PNG\r\n\x1a\n' and data[12:16] == b'IHDR':
                    w, h = struct.unpack('>ii', data[16:24])
                    return w, h
        except Exception:
            pass
        return None, None

    def start_evdev_listener(self):
        """Starts background threads to intercept hardware keypress events for Caps Lock across all keyboards."""
        def listen_device(device_path, device_name):
            try:
                import evdev
                from evdev import ecodes
                
                device = evdev.InputDevice(device_path)
                print(f"[evdev] Listening for Caps Lock events on: {device_name} ({device_path})")
                
                # Resolve trigger.sh path dynamically (AppImage-safe)
                appdir = os.environ.get("APPDIR")
                if appdir:
                    trigger_path = os.path.join(appdir, "usr", "bin", "trigger.sh")
                else:
                    here = os.path.dirname(os.path.abspath(__file__))
                    trigger_path = os.path.join(here, "trigger.sh")
                    
                if not os.path.exists(trigger_path):
                    trigger_path = os.path.expanduser("~/.config/heyclicky/trigger.sh")

                for event in device.read_loop():
                    if event.type == ecodes.EV_KEY:
                        key_event = evdev.categorize(event)
                        keycode = key_event.keycode
                        is_caps = False
                        if isinstance(keycode, str):
                            is_caps = (keycode == 'KEY_CAPSLOCK')
                        elif isinstance(keycode, list):
                            is_caps = ('KEY_CAPSLOCK' in keycode)
                            
                        if is_caps:
                            if key_event.keystate == key_event.key_down:
                                print(f"[evdev] Caps Lock Pressed on {device_name} -> Start Capture")
                                subprocess.run([trigger_path, "press"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            elif key_event.keystate == key_event.key_up:
                                print(f"[evdev] Caps Lock Released on {device_name} -> Run AI Brain")
                                subprocess.run([trigger_path, "release"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                # Thread exits on device disconnect
                print(f"[evdev] Stopped listening to keyboard {device_name} ({device_path}): {e}", file=sys.stderr)

        def manage_listeners():
            try:
                import evdev
                from evdev import ecodes
            except ImportError:
                print("Warning: 'evdev' library not installed. Global hardware hotkey disabled.", file=sys.stderr)
                return

            active_devices = {}  # path -> thread

            while True:
                try:
                    paths = evdev.list_devices()
                    current_keyboards = {}
                    
                    for path in paths:
                        try:
                            dev = evdev.InputDevice(path)
                            caps = dev.capabilities()
                            if ecodes.EV_KEY in caps and ecodes.KEY_CAPSLOCK in caps[ecodes.EV_KEY]:
                                current_keyboards[path] = dev.name
                        except Exception:
                            pass
                    
                    # Cleanup disconnected threads
                    stale_paths = [p for p in active_devices if p not in current_keyboards]
                    for p in stale_paths:
                        active_devices.pop(p)
                        
                    # Spawn new listener threads for newly connected keyboards
                    for path, name in current_keyboards.items():
                        if path not in active_devices:
                            print(f"[evdev] Keyboard detected: {name} ({path})")
                            t = threading.Thread(target=listen_device, args=(path, name), daemon=True)
                            t.start()
                            active_devices[path] = t
                except PermissionError:
                    print("Error: Permission denied reading input devices.", file=sys.stderr)
                    print("Please run: sudo usermod -aG input $USER and configure setfacl.", file=sys.stderr)
                    subprocess.run(["notify-send", "HeyClicky Alert", "Permission denied reading input devices. Please configure udev rules."], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    import time
                    time.sleep(10)
                except Exception as e:
                    print(f"Error checking input devices: {e}", file=sys.stderr)
                
                import time
                time.sleep(3)

        thread = threading.Thread(target=manage_listeners, daemon=True)
        thread.start()

    def reposition_on_active_monitor(self):
        """Checks where the mouse is and dynamically repositions the overlay to that monitor."""
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        pointer = seat.get_pointer()
        screen, x, y = pointer.get_position()
        monitor = display.get_monitor_at_point(x, y)
        
        if hasattr(self, 'current_monitor') and self.current_monitor == monitor:
            return
        
        self.current_monitor = monitor
        print(f"Repositioning overlay window to monitor under pointer: {monitor}")
        
        if self.using_layer_shell:
            try:
                GtkLayerShell.set_monitor(self, monitor)
            except Exception as e:
                print(f"Failed to dynamically move Layer Shell monitor: {e}", file=sys.stderr)
        else:
            try:
                self.fullscreen_on_monitor(screen, monitor)
            except Exception as e:
                print(f"Failed to dynamically move fullscreen monitor: {e}", file=sys.stderr)

    def on_realize(self, widget):
        window = widget.get_window()
        window.set_pass_through(True)
        empty = cairo.Region()
        window.input_shape_combine_region(empty, 0, 0)
        parent = window.get_parent()
        if parent:
            parent.set_pass_through(True)
            parent.input_shape_combine_region(empty, 0, 0)
        GLib.idle_add(self._ensure_pass_through)

    def _ensure_pass_through(self):
        window = self.get_window()
        if window is None:
            return False
        window.set_pass_through(True)
        empty = cairo.Region()
        window.input_shape_combine_region(empty, 0, 0)
        parent = window.get_parent()
        if parent:
            parent.set_pass_through(True)
        return False

    def on_poll_state(self):
        """Polls /tmp/heyclicky_state.json to update target positions."""
        if not os.path.exists(STATE_FILE):
            self.state = "idle"
            self.target_x = None
            self.target_y = None
            self.target_label = None
            return True

        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)

            new_state = data.get("state", "idle")
            if new_state != self.state:
                self.last_state_change = time.time()
            self.state = new_state
            self.response_text = data.get("text", "")

            # Staleness guard: reset to idle if state has been active too long
            elapsed = time.time() - self.last_state_change
            timeout = self.state_timeout.get(self.state)
            if timeout and elapsed > timeout:
                print(f"State '{self.state}' timed out after {elapsed:.0f}s, resetting to idle")
                self.state = "idle"
                self.target_x = None
                self.target_y = None
                self.target_label = None
                return True

            # Reposition overlay to monitor under cursor during active states
            if self.state in ("processing", "responding"):
                self.reposition_on_active_monitor()

            point = data.get("point")

            if self.state == "responding" and point:
                raw_x = point.get("x")
                raw_y = point.get("y")

                # Dynamic coordinate translation logic
                screen_png = f"/tmp/heyclicky_screen_{os.getuid()}.png"
                w_phys, h_phys = self.get_png_size(screen_png)
                w_log = self.get_allocated_width()
                h_log = self.get_allocated_height()

                if w_phys and h_phys and w_log > 0 and h_log > 0:
                    display = Gdk.Display.get_default()
                    seat = display.get_default_seat()
                    pointer = seat.get_pointer()
                    _, px, py = pointer.get_position()
                    monitor = display.get_monitor_at_point(px, py)
                    geom = monitor.get_geometry()

                    default_screen = Gdk.Screen.get_default()
                    w_screen = default_screen.get_width()
                    h_screen = default_screen.get_height()

                    aspect_phys = w_phys / h_phys
                    aspect_monitor = geom.width / geom.height

                    if abs(aspect_phys - aspect_monitor) < 0.1:
                        scale_x = w_log / w_phys
                        scale_y = h_log / h_phys
                        self.target_x = raw_x * scale_x
                        self.target_y = raw_y * scale_y
                    else:
                        scale_x = w_screen / w_phys
                        scale_y = h_screen / h_phys
                        self.target_x = (raw_x * scale_x) - geom.x
                        self.target_y = (raw_y * scale_y) - geom.y
                else:
                    self.target_x = raw_x
                    self.target_y = raw_y

                self.target_label = point.get("label")
            else:
                self.target_x = None
                self.target_y = None
                self.target_label = None
        except Exception:
            pass

        return True

    def on_anim_tick(self):
        try:
            return self._on_anim_tick()
        except Exception:
            return True

    def _on_anim_tick(self):
        needs_redraw = False
        
        # Follow mouse pointer in real-time for cursor-glued states
        if self.state in ("idle", "listening", "processing") or (self.state == "responding" and self.target_x is None):
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            _, px, py = pointer.get_position()
            
            # Reposition to monitor under pointer dynamically
            self.reposition_on_active_monitor()
            
            geom = self.current_monitor.get_geometry() if self.current_monitor else display.get_monitor_at_point(px, py).get_geometry()
            
            # Float next to the mouse cursor (offset)
            self.target_x = px - geom.x + 25
            self.target_y = py - geom.y + 20
            
            # Animate spin and pulse if needed
            if self.state == "processing":
                if not hasattr(self, 'spin_angle'):
                    self.spin_angle = 0.0
                self.spin_angle = (self.spin_angle + 0.08) % (2 * math.pi)
            
            if self.state in ("listening", "processing"):
                if not hasattr(self, 'pulse_angle'):
                    self.pulse_angle = 0.0
                self.pulse_angle = (self.pulse_angle + 0.05) % (2 * math.pi)
                self.pulse_val = math.sin(self.pulse_angle) * 0.3 + 0.7
            
            # Ensure the overlay is always visible during idle/active states
            if self.opacity < 1.0:
                self.opacity = min(1.0, self.opacity + 0.1)
            needs_redraw = True
        
        if self.target_x is not None and self.target_y is not None:
            # Initialize position if it's the first frame
            if self.current_x is None or self.current_y is None:
                self.current_x = self.target_x
                self.current_y = self.target_y
                
            # Easing translation (glide towards target)
            dx = self.target_x - self.current_x
            dy = self.target_y - self.current_y
            
            self.current_x += dx * 0.15
            self.current_y += dy * 0.15
            
            # Fade in
            if self.state == "responding" and self.target_x is not None:
                if self.opacity < 1.0:
                    self.opacity = min(1.0, self.opacity + 0.1)
                    needs_redraw = True
                
            # Check if we still need to animate movement
            if abs(dx) > 0.5 or abs(dy) > 0.5:
                needs_redraw = True
        else:
            # Fade out
            if self.opacity > 0.0:
                self.opacity = max(0.0, self.opacity - 0.1)
                needs_redraw = True
            else:
                self.current_x = None
                self.current_y = None

        if needs_redraw or self.opacity > 0.0:
            self.queue_draw()
            
        return True

    def wrap_text(self, ctx, text, max_width):
        """Wraps text so that no line exceeds max_width pixels when rendered with the current font settings."""
        words = text.split()
        if not words:
            return []
        
        lines = []
        current_line = []
        
        for word in words:
            test_line = " ".join(current_line + [word])
            extents = ctx.text_extents(test_line)
            if extents.width <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
                    current_line = []
                    
        if current_line:
            lines.append(" ".join(current_line))
            
        return lines

    def draw_rounded_rect(self, ctx, x, y, width, height, radius):
        """Draws a rounded rectangle path in cairo."""
        ctx.new_sub_path()
        ctx.arc(x + width - radius, y + radius, radius, -math.pi/2, 0)
        ctx.arc(x + width - radius, y + height - radius, radius, 0, math.pi/2)
        ctx.arc(x + radius, y + height - radius, radius, math.pi/2, math.pi)
        ctx.arc(x + radius, y + radius, radius, math.pi, 3*math.pi/2)
        ctx.close_path()

    def on_draw(self, widget, ctx):
        # Clear screen with transparent alpha
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.set_operator(cairo.Operator.SOURCE)
        ctx.paint()
        ctx.set_operator(cairo.Operator.OVER)

        # Do not draw if faded out
        if self.opacity <= 0.0 or self.current_x is None or self.current_y is None:
            return True

        cx, cy = self.current_x, self.current_y

        if self.state == "listening":
            # Draw beautiful pulsing audio waveform centered at (cx, cy)
            import time
            import random
            t = time.time() * 15
            
            if not hasattr(self, 'wave_noise'):
                self.wave_noise = 0.5
            self.wave_noise = max(0.0, min(1.0, self.wave_noise + random.uniform(-0.15, 0.15)))
            
            pulse = getattr(self, 'pulse_val', 0.8)
            heights = [
                3 + (math.sin(t) * 3 + 2) * self.wave_noise,
                3 + (math.cos(t * 0.8) * 5 + 4) * self.wave_noise,
                3 + (math.sin(t * 1.2) * 8 + 6) * self.wave_noise,
                3 + (math.cos(t * 0.9) * 5 + 4) * self.wave_noise,
                3 + (math.sin(t * 0.7) * 3 + 2) * self.wave_noise,
            ]
            
            for i, h in enumerate(heights):
                bx = cx - 9 + i * 4
                by = cy - h / 2
                self.draw_rounded_rect(ctx, bx, by, 2.0, h, 1.0)
                ctx.set_source_rgba(0.20, 0.50, 1.0, self.opacity) # #3380FF
                ctx.fill()
                
            return True

        elif self.state == "processing":
            # Draw beautiful spinning neon ring centered at (cx, cy)
            spin = getattr(self, 'spin_angle', 0.0)
            pulse = getattr(self, 'pulse_val', 0.8)
            
            radius = 7.0
            
            # 1. Outer breathing glow
            ctx.set_source_rgba(0.20, 0.50, 1.0, 0.15 * pulse * self.opacity)
            ctx.arc(cx, cy, radius + 4, 0, 2 * math.pi)
            ctx.fill()
            
            # 2. Track ring
            ctx.set_source_rgba(0.20, 0.50, 1.0, 0.15 * self.opacity)
            ctx.set_line_width(2.0)
            ctx.arc(cx, cy, radius, 0, 2 * math.pi)
            ctx.stroke()
            
            # 3. Spinning active arc
            ctx.set_source_rgba(0.20, 0.50, 1.0, 1.0 * self.opacity)
            ctx.set_line_width(2.5)
            ctx.arc(cx, cy, radius, spin, spin + 1.4 * math.pi)
            ctx.stroke()
            
            return True

        # Draw neon blue cursor triangle pointing at or rotated next to (cx, cy)
        # 1. Outer Glow (faint)
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(math.radians(-35.0))
        
        size = 14.0
        height = size * math.sqrt(3.0) / 2.0
        
        ctx.move_to(0, -height / 1.5)
        ctx.line_to(-size / 2, height / 3.0)
        ctx.line_to(size / 2, height / 3.0)
        ctx.close_path()
        
        ctx.set_source_rgba(0.20, 0.50, 1.0, 0.4 * self.opacity)
        ctx.set_line_width(4.0)
        ctx.stroke()
        ctx.restore()

        # 2. Solid Inner Triangle
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(math.radians(-35.0))
        
        ctx.move_to(0, -height / 1.5)
        ctx.line_to(-size / 2, height / 3.0)
        ctx.line_to(size / 2, height / 3.0)
        ctx.close_path()
        
        ctx.set_source_rgba(0.20, 0.50, 1.0, self.opacity)
        ctx.fill()
        ctx.restore()

        # Draw Label Bubble if text exists (pointing target label)
        if self.target_label:
            ctx.select_font_face("Outfit", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(11.0)
            
            # Get text dimensions to scale bubble
            extents = ctx.text_extents(self.target_label)
            tw, th = extents.width, extents.height
            
            # Bubble layout calculations
            pad_x = 8
            pad_y = 4
            bw = tw + (pad_x * 2)
            bh = th + (pad_y * 2)
            bx = cx + 10
            by = cy + 18
            
            # Draw semi-transparent bubble backdrop
            ctx.set_source_rgba(0.20, 0.50, 1.0, 1.0 * self.opacity)
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 6)
            ctx.fill()
            
            # Draw neon shadow glow
            ctx.set_source_rgba(0.20, 0.50, 1.0, 0.5 * self.opacity)
            ctx.set_line_width(2.0)
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 6)
            ctx.stroke()
            
            # Render label text
            ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0 * self.opacity)
            ctx.move_to(bx + pad_x, by + pad_y + th - 1.0)
            ctx.show_text(self.target_label)

        # Draw Large Text Response Bubble next to mouse cursor if text exists
        if self.state == "responding" and hasattr(self, 'response_text') and self.response_text:
            ctx.select_font_face("Outfit", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(13.0)
            
            # Wrap text to max 260 width
            lines = self.wrap_text(ctx, self.response_text, 260.0)
            
            # Calculate bounds
            max_line_w = 0
            for line in lines:
                extents = ctx.text_extents(line)
                if extents.width > max_line_w:
                    max_line_w = extents.width
            
            line_height = 18.0
            pad_x = 14.0
            pad_y = 10.0
            
            bw = max_line_w + (pad_x * 2)
            bh = len(lines) * line_height + (pad_y * 2) - 4
            
            # Position it to the right and slightly below/above the actual mouse position
            display = Gdk.Display.get_default()
            seat = display.get_default_seat()
            pointer = seat.get_pointer()
            _, px, py = pointer.get_position()
            geom = self.current_monitor.get_geometry() if hasattr(self, 'current_monitor') and self.current_monitor else display.get_monitor_at_point(px, py).get_geometry()
            
            local_px = px - geom.x
            local_py = py - geom.y
            
            bx = local_px + 22.0
            by = local_py + 6.0
            
            # Clamp to screen bounds
            w_log = self.get_allocated_width()
            h_log = self.get_allocated_height()
            if bx + bw > w_log:
                bx = local_px - 22.0 - bw
            if by + bh > h_log:
                by = local_py - 6.0 - bh
                
            bx = max(10.0, min(bx, w_log - bw - 10.0))
            by = max(10.0, min(by, h_log - bh - 10.0))
            
            # Draw dark surface background
            ctx.set_source_rgba(0.09, 0.10, 0.09, 0.95 * self.opacity) # surface1
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 10)
            ctx.fill()
            
            # Draw subtle border outline
            ctx.set_source_rgba(0.22, 0.23, 0.22, 0.5 * self.opacity) # borderSubtle
            ctx.set_line_width(0.8)
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 10)
            ctx.stroke()
            
            # Render lines
            ctx.set_source_rgba(0.93, 0.93, 0.93, 1.0 * self.opacity) # textPrimary
            for idx, line in enumerate(lines):
                extents = ctx.text_extents(line)
                ctx.move_to(bx + pad_x, by + pad_y + idx * line_height + 12.0)
                ctx.show_text(line)

        return True

import shutil

def sanity_check_dependencies(session_type):
    """Verifies that critical host binaries (mpv, screenshot, and audio tools) are installed."""
    missing = []
    
    # 1. Check mpv and curl
    if not shutil.which("mpv"):
        missing.append("mpv (required for voice playback)")
    if not shutil.which("curl"):
        missing.append("curl (required for API calls)")
        
    # 2. Check screenshot tools depending on environment
    screenshot_ok = False
    if session_type == "wayland":
        # Check standard Wayland CLI screenshot tools
        if shutil.which("grim") or shutil.which("spectacle") or shutil.which("gnome-screenshot"):
            screenshot_ok = True
        else:
            # Check pydbus / portal
            try:
                import gi
                gi.require_version('GLib', '2.0')
                from gi.repository import GLib
                from pydbus import SessionBus
                screenshot_ok = True
            except Exception:
                pass
    else:
        # X11 tools
        if shutil.which("maim") or shutil.which("gnome-screenshot") or shutil.which("spectacle"):
            screenshot_ok = True
            
    if not screenshot_ok:
        if session_type == "wayland":
            missing.append("a Wayland screenshot utility (grim, spectacle, or gnome-screenshot)")
        else:
            missing.append("an X11 screenshot utility (maim, gnome-screenshot, or spectacle)")
            
    # 3. Check audio recording tools (PipeWire or PulseAudio)
    if not shutil.which("pw-record") and not shutil.which("parecord"):
        missing.append("an audio recording utility (pw-record or parecord)")
            
    if missing:
        msg = "Missing dependencies: " + ", ".join(missing)
        subprocess.run(["notify-send", "HeyClicky Error", msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sys.exit(1)

def main():
    # Force Gdk to use Wayland backend if Wayland is active, else X11
    # This prevents backend mapping warnings or crashes on mixed environments
    env_file = os.path.expanduser("~/.config/heyclicky/env.conf")
    session_type = "wayland"
    overlay_method = ""
    if os.path.exists(env_file):
        try:
            with open(env_file, "r") as f:
                for line in f:
                    if "SESSION_TYPE" in line:
                        session_type = line.split("=")[-1].strip().strip('"').strip("'")
                    if "OVERLAY_METHOD" in line:
                        overlay_method = line.split("=")[-1].strip().strip('"').strip("'")
        except Exception:
            pass

    # Run host binary checks before initializing GTK overlay
    sanity_check_dependencies(session_type)

    # On KDE Wayland, GtkLayerShell overlay is unreliable (invisible cursor, broken pass-through).
    # Use X11 (via XWayland) which works correctly with fullscreen+keep_above+input_shape_combine_region.
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if overlay_method == "x11":
        os.environ["GDK_BACKEND"] = "x11"
    elif overlay_method == "wayland":
        os.environ["GDK_BACKEND"] = "wayland"
    elif session_type == "wayland" and "kde" not in desktop:
        os.environ["GDK_BACKEND"] = "wayland"
    else:
        os.environ["GDK_BACKEND"] = "x11"

    # Load CSS provider to enforce transparent window background across themes
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(b"""
        window {
            background-color: rgba(0, 0, 0, 0);
            background: transparent;
        }
    """)
    try:
        screen = Gdk.Screen.get_default()
        if screen:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
    except Exception as e:
        print(f"Warning: Could not set CSS provider: {e}", file=sys.stderr)

    app = HeyClickyOverlayWindow()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
