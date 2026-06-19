import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import json

# Adjust path to import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Import from overlay without triggering GTK initialization crashes in test
from overlay import HeyClickyOverlayWindow

class DummyOverlay:
    def __init__(self):
        self.state = "idle"
        self.response_text = ""
        self.target_x = None
        self.target_y = None
        self.target_label = None
        self.current_monitor = None
        self.opacity = 0.0
        
        # Mocks for Gtk/Gdk window methods used in on_poll_state
        self.get_allocated_width = MagicMock(return_value=800)
        self.get_allocated_height = MagicMock(return_value=600)
        self.reposition_on_active_monitor = MagicMock()

    # Bind functions directly from HeyClickyOverlayWindow
    wrap_text = HeyClickyOverlayWindow.wrap_text
    get_png_size = HeyClickyOverlayWindow.get_png_size
    on_poll_state = HeyClickyOverlayWindow.on_poll_state

class TestOverlayWindow(unittest.TestCase):

    def setUp(self):
        self.window = DummyOverlay()

    def test_wrap_text(self):
        # Create a mock cairo context
        ctx = MagicMock()
        # Mock text_extents to return different widths based on text length
        def side_effect(text):
            extents = MagicMock()
            extents.width = len(text) * 5 # Simulating character width
            return extents
        ctx.text_extents.side_effect = side_effect
        
        text = "This is a test of the text wrapping function in the overlay"
        # Wrap to 100 pixels (roughly 20 characters since 20 * 5 = 100)
        lines = self.window.wrap_text(ctx, text, 100)
        self.assertTrue(len(lines) > 1)
        # Ensure all words are present
        reconstructed = " ".join(lines)
        self.assertEqual(reconstructed, text)

    def test_get_png_size(self):
        # Mock open to return PNG header bytes (width=800, height=600)
        png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x03\x20\x00\x00\x02\x58\x08\x06\x00\x00\x00'
        # Width: \x03\x20 -> 800
        # Height: \x02\x58 -> 600
        with patch('builtins.open', mock_open(read_data=png_data)):
            w, h = self.window.get_png_size("fake.png")
            self.assertEqual(w, 800)
            self.assertEqual(h, 600)

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open)
    def test_on_poll_state_idle(self, mock_open_file, mock_exists):
        mock_exists.return_value = False
        
        # Calling poll state when state file is missing should reset to idle
        res = self.window.on_poll_state()
        self.assertTrue(res)
        self.assertEqual(self.window.state, "idle")
        self.assertIsNone(self.window.target_x)

    @patch('os.path.exists')
    @patch('builtins.open')
    def test_on_poll_state_responding(self, mock_open_file, mock_exists):
        mock_exists.return_value = True
        
        # Mock JSON read
        state_data = {
            "state": "responding",
            "text": "Hello world",
            "point": {"x": 400, "y": 300, "label": "button"}
        }
        mock_open_file.return_value.__enter__.return_value.read.return_value = json.dumps(state_data)
        
        # We mock get_png_size to return 800x600 (aspect 1.33)
        self.window.get_png_size = MagicMock(return_value=(800, 600))
        
        # Mock Gdk/monitor attributes to simulate coordinate resolution
        display = MagicMock()
        monitor = MagicMock()
        geom = MagicMock()
        geom.width = 800
        geom.height = 600
        geom.x = 0
        geom.y = 0
        monitor.get_geometry.return_value = geom
        
        with patch('gi.repository.Gdk.Display.get_default') as mock_get_default, \
             patch('gi.repository.Gdk.Screen.get_default') as mock_get_screen_default:
            
            mock_get_default.return_value = display
            pointer_obj = MagicMock()
            pointer_obj.get_position.return_value = (None, 100, 100)
            display.get_default_seat.return_value.get_pointer.return_value = pointer_obj
            display.get_monitor_at_point.return_value = monitor
            
            screen = MagicMock()
            screen.get_width.return_value = 800
            screen.get_height.return_value = 600
            mock_get_screen_default.return_value = screen
            
            res = self.window.on_poll_state()
            
            self.assertTrue(res)
            self.assertEqual(self.window.state, "responding")
            self.assertEqual(self.window.response_text, "Hello world")
            # 400 x (800/800) = 400
            self.assertEqual(self.window.target_x, 400)
            self.assertEqual(self.window.target_y, 300)
            self.assertEqual(self.window.target_label, "button")

if __name__ == '__main__':
    unittest.main()
