import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust path to import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
from capture import read_env_conf, capture_x11, capture_wayland

class TestCaptureEngine(unittest.TestCase):

    @patch('os.path.exists')
    @patch('builtins.open')
    def test_read_env_conf(self, mock_open_file, mock_exists):
        mock_exists.return_value = True
        env_content = """
        SESSION_TYPE="wayland"
        DESKTOP="hyprland"
        CAPTURE_METHOD="dbus-screencast"
        """
        mock_open_file.return_value.__enter__.return_value = env_content.splitlines()
        
        config = read_env_conf()
        self.assertEqual(config.get("SESSION_TYPE"), "wayland")
        self.assertEqual(config.get("DESKTOP"), "hyprland")
        self.assertEqual(config.get("CAPTURE_METHOD"), "dbus-screencast")

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_capture_x11_maim(self, mock_run, mock_which):
        # Simulate maim exists
        mock_which.side_effect = lambda x: x == "maim"
        mock_run.return_value.returncode = 0
        
        res = capture_x11()
        self.assertTrue(res)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][0], "maim")

    @patch('shutil.which')
    @patch('subprocess.run')
    def test_capture_x11_fallback_gnome(self, mock_run, mock_which):
        # Simulate maim doesn't exist, but gnome-screenshot does
        mock_which.side_effect = lambda x: x == "gnome-screenshot"
        mock_run.return_value.returncode = 0
        
        res = capture_x11()
        self.assertTrue(res)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][0], "gnome-screenshot")

    @patch('shutil.which')
    @patch('subprocess.run')
    @patch('os.environ.get')
    def test_capture_wayland_kde_spectacle(self, mock_env, mock_run, mock_which):
        mock_env.return_value = "kde"
        mock_which.side_effect = lambda x: x == "spectacle"
        mock_run.return_value.returncode = 0
        
        res = capture_wayland()
        self.assertTrue(res)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0][0], "spectacle")

    @patch('shutil.which')
    @patch('subprocess.run')
    @patch('os.environ.get')
    def test_capture_wayland_grim_hyprland(self, mock_env, mock_run, mock_which):
        mock_env.return_value = "hyprland"
        # Simulate grim and jq exist, but no hyprctl
        mock_which.side_effect = lambda x: x in ("grim", "jq")
        mock_run.return_value.returncode = 0
        
        res = capture_wayland()
        self.assertTrue(res)
        # Grim fallback (no monitor name resolved since hyprctl failed or wasn't mocked)
        self.assertEqual(mock_run.call_args[0][0][0], "grim")

if __name__ == '__main__':
    unittest.main()
