#!/usr/bin/env python3
import os
import sys
import json
import math
import threading
import subprocess
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import cairo

STATE_FILE = "/tmp/clicky_state.json"

class ClickyOverlayWindow(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        
        # Configure window characteristics for a full-screen HUD overlay
        self.set_title("HeyClicky Overlay")
        self.set_decorated(False)
        self.fullscreen()
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)

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
        
        self.current_x = None
        self.current_y = None
        self.opacity = 0.0  # Fade animation
        
        # Schedule configuration of click-through and polling loop once realized
        self.connect("realize", self.on_realize)
        
        # High frequency animation tick (60 FPS ~ 16ms)
        GLib.timeout_add(16, self.on_anim_tick)
        
        # Slightly slower state file polling tick (100ms)
        GLib.timeout_add(100, self.on_poll_state)

        # Start the global evdev hardware hotkey listener
        self.start_evdev_listener()

    def start_evdev_listener(self):
        """Starts a background thread to intercept hardware keypress events for Caps Lock."""
        def listen():
            try:
                import evdev
                from evdev import ecodes
            except ImportError:
                print("Warning: 'evdev' library not installed in Python environment. Global hardware hotkey disabled.", file=sys.stderr)
                return

            keyboard_device = None
            try:
                # Iterate all input devices to find the hardware keyboard
                devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
                for device in devices:
                    capabilities = device.capabilities()
                    if ecodes.EV_KEY in capabilities:
                        if ecodes.KEY_CAPSLOCK in capabilities[ecodes.EV_KEY]:
                            keyboard_device = device
                            break
            except PermissionError:
                print("Error: Permission denied reading input devices.", file=sys.stderr)
                print("To fix, please run: sudo usermod -aG input $USER and reboot.", file=sys.stderr)
                return
            except Exception as e:
                print(f"Error initializing input devices: {e}", file=sys.stderr)
                return

            if not keyboard_device:
                print("No input device detected with KEY_CAPSLOCK capability.", file=sys.stderr)
                return

            print(f"Intercepting global Caps Lock events on: {keyboard_device.name} ({keyboard_device.path})")

            # Resolve the absolute path of trigger.sh dynamically next to this script
            here = os.path.dirname(os.path.abspath(__file__))
            trigger_path = os.path.join(here, "trigger.sh")
            if not os.path.exists(trigger_path):
                trigger_path = os.path.expanduser("~/Heyclicky_linux/clicky/trigger.sh")

            try:
                for event in keyboard_device.read_loop():
                    if event.type == ecodes.EV_KEY:
                        key_event = evdev.categorize(event)
                        if key_event.keycode == 'KEY_CAPSLOCK':
                            if key_event.keystate == key_event.key_down:
                                print("[evdev] Caps Lock Pressed -> Start Capture")
                                subprocess.run([trigger_path, "press"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            elif key_event.keystate == key_event.key_up:
                                print("[evdev] Caps Lock Released -> Run AI Brain")
                                subprocess.run([trigger_path, "release"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except PermissionError:
                print("Error: Read permissions lost for input device. Run: sudo usermod -aG input $USER", file=sys.stderr)
            except Exception as e:
                print(f"evdev keyboard listener error: {e}", file=sys.stderr)

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def on_realize(self, widget):
        # Configure input shape region to be empty so the entire window is click-through
        region = cairo.Region()
        widget.get_window().input_shape_combine_region(region, 0, 0)
        print("Overlay window realized and configured for click-through.")

    def on_poll_state(self):
        """Polls /tmp/clicky_state.json to update target positions."""
        if not os.path.exists(STATE_FILE):
            self.state = "idle"
            self.target_x = None
            self.target_y = None
            self.target_label = None
            return True

        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                
            self.state = data.get("state", "idle")
            point = data.get("point")
            
            if self.state == "responding" and point:
                self.target_x = point.get("x")
                self.target_y = point.get("y")
                self.target_label = point.get("label")
            else:
                self.target_x = None
                self.target_y = None
                self.target_label = None
        except Exception:
            # Silently ignore parsing errors from race conditions writing the JSON
            pass
            
        return True

    def on_anim_tick(self):
        """Updates animation positions and triggers redrawing."""
        needs_redraw = False
        
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

        # Draw neon blue cursor triangle pointing at (cx, cy)
        # We draw layers to simulate a glow effect
        
        # 1. Outer Glow (Large, faint)
        ctx.set_source_rgba(0.0, 0.74, 1.0, 0.18 * self.opacity)
        ctx.move_to(cx, cy)
        ctx.line_to(cx - 20, cy + 32)
        ctx.line_to(cx + 20, cy + 32)
        ctx.close_path()
        ctx.fill()

        # 2. Medium Glow
        ctx.set_source_rgba(0.0, 0.74, 1.0, 0.4 * self.opacity)
        ctx.move_to(cx, cy)
        ctx.line_to(cx - 15, cy + 24)
        ctx.line_to(cx + 15, cy + 24)
        ctx.close_path()
        ctx.fill()

        # 3. Solid Inner Triangle
        ctx.set_source_rgba(0.0, 0.82, 1.0, 1.0 * self.opacity)
        ctx.move_to(cx, cy)
        ctx.line_to(cx - 10, cy + 16)
        ctx.line_to(cx + 10, cy + 16)
        ctx.close_path()
        ctx.fill()

        # 4. White tip highlights
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.9 * self.opacity)
        ctx.move_to(cx, cy)
        ctx.line_to(cx - 4, cy + 7)
        ctx.line_to(cx + 4, cy + 7)
        ctx.close_path()
        ctx.fill()

        # Draw Label Bubble if text exists
        if self.target_label:
            ctx.select_font_face("Outfit", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(13.0)
            
            # Get text dimensions to scale bubble
            extents = ctx.text_extents(self.target_label)
            tw, th = extents.width, extents.height
            
            # Bubble layout calculations
            pad_x = 12
            pad_y = 8
            bw = tw + (pad_x * 2)
            bh = th + (pad_y * 2)
            bx = cx - (bw / 2)
            by = cy + 28  # Offset below the triangle pointer
            
            # Draw semi-transparent bubble backdrop
            ctx.set_source_rgba(0.04, 0.05, 0.09, 0.85 * self.opacity)
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 6)
            ctx.fill()
            
            # Draw neon border highlight
            ctx.set_source_rgba(0.0, 0.74, 1.0, 0.5 * self.opacity)
            ctx.set_line_width(1.5)
            self.draw_rounded_rect(ctx, bx, by, bw, bh, 6)
            ctx.stroke()
            
            # Render label text
            ctx.set_source_rgba(1.0, 1.0, 1.0, 1.0 * self.opacity)
            # Center alignment inside rect
            ctx.move_to(bx + pad_x - extents.x_bearing, by + pad_y + th)
            ctx.show_text(self.target_label)

        return True

def main():
    # Force Gdk to use Wayland backend if Wayland is active, else X11
    # This prevents backend mapping warnings or crashes on mixed environments
    env_file = os.path.expanduser("~/.config/clicky/env.conf")
    session_type = "wayland"
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if "SESSION_TYPE" in line:
                    session_type = line.split("=")[-1].strip().strip('"').strip("'")
                    
    if session_type == "wayland":
        os.environ["GDK_BACKEND"] = "wayland"
    else:
        os.environ["GDK_BACKEND"] = "x11"

    # Load CSS provider to enforce transparent window background across themes
    screen = Gdk.Screen.get_default()
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(b"""
        window {
            background-color: rgba(0, 0, 0, 0);
            background: transparent;
        }
    """)
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    app = ClickyOverlayWindow()
    app.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
