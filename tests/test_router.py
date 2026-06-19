import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import json

# Adjust path to import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))
from brain import get_llm_response, load_env_variables

class TestUniversalLLMRouter(unittest.TestCase):
    
    @patch('os.path.exists')
    @patch('subprocess.run')
    def test_openai_provider(self, mock_run, mock_exists):
        # Setup: simulate no screenshot
        mock_exists.return_value = False
        
        # Mock successful subprocess response for OpenAI
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "choices": [
                {
                    "message": {
                        "content": "Sure, here is the button [POINT:100,200:click]"
                    }
                }
            ]
        })
        mock_run.return_value = mock_response
        
        credentials = {"OPENAI_API_KEY": "test_openai_key"}
        response = get_llm_response("openai", credentials, "Show me the button")
        
        # Verify response parsing
        self.assertEqual(response, "Sure, here is the button [POINT:100,200:click]")
        
        # Verify subprocess parameters
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("https://api.openai.com/v1/chat/completions", args)
        self.assertIn("Authorization: Bearer test_openai_key", args)
        
        # Verify payload content
        payload_str = args[args.index("-d") + 1]
        payload = json.loads(payload_str)
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["messages"][1]["content"][0]["text"], "Show me the button")

    @patch('os.path.exists')
    @patch('subprocess.run')
    def test_gemini_provider(self, mock_run, mock_exists):
        # Setup: simulate no screenshot
        mock_exists.return_value = False
        
        # Mock successful subprocess response for Gemini
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Clicked that for you [POINT:300,400:button]"}
                        ]
                    }
                }
            ]
        })
        mock_run.return_value = mock_response
        
        credentials = {"GEMINI_API_KEY": "test_gemini_key"}
        response = get_llm_response("gemini", credentials, "Click the button")
        
        # Verify response parsing
        self.assertEqual(response, "Clicked that for you [POINT:300,400:button]")
        
        # Verify subprocess parameters
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertTrue(any("gemini-1.5-flash:generateContent?key=test_gemini_key" in arg for arg in args))
        
        # Verify payload content
        payload_str = args[args.index("-d") + 1]
        payload = json.loads(payload_str)
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Click the button")

    @patch('os.path.exists')
    @patch('subprocess.run')
    def test_ollama_provider(self, mock_run, mock_exists):
        # Setup: simulate no screenshot
        mock_exists.return_value = False
        
        # Mock successful subprocess response for Ollama
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "response": "Done! [POINT:500,600:input]"
        })
        mock_run.return_value = mock_response
        
        credentials = {}
        response = get_llm_response("ollama", credentials, "Type here")
        
        # Verify response parsing
        self.assertEqual(response, "Done! [POINT:500,600:input]")
        
        # Verify subprocess parameters
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("http://localhost:11434/api/generate", args)
        
        # Verify payload content
        payload_str = args[args.index("-d") + 1]
        payload = json.loads(payload_str)
        self.assertEqual(payload["model"], "llava")
        self.assertFalse(payload["stream"])

    @patch('os.path.exists')
    @patch('subprocess.run')
    def test_anthropic_provider(self, mock_run, mock_exists):
        # Setup: simulate no screenshot
        mock_exists.return_value = False
        
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "content": [
                {"type": "text", "text": "Claude here [POINT:150,250:icon]"}
            ]
        })
        mock_run.return_value = mock_response
        
        credentials = {"ANTHROPIC_API_KEY": "test_anthropic_key"}
        response = get_llm_response("anthropic", credentials, "Click icon")
        
        self.assertEqual(response, "Claude here [POINT:150,250:icon]")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("https://api.anthropic.com/v1/messages", args)
        self.assertIn("x-api-key: test_anthropic_key", args)

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=b"fake_image_bytes")
    @patch('subprocess.run')
    def test_openai_with_screenshot(self, mock_run, mock_open_file, mock_exists):
        # Setup: simulate screenshot exists
        mock_exists.return_value = True
        
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "choices": [{"message": {"content": "Found it!"}}]
        })
        mock_run.return_value = mock_response
        
        credentials = {"OPENAI_API_KEY": "test_openai_key"}
        response = get_llm_response("openai", credentials, "Look at this")
        
        self.assertEqual(response, "Found it!")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        payload_str = args[args.index("-d") + 1]
        payload = json.loads(payload_str)
        
        # Verify base64 image data is passed as a data URI
        content = payload["messages"][1]["content"]
        self.assertEqual(len(content), 2)
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data=b"fake_image_bytes")
    @patch('subprocess.run')
    def test_gemini_with_screenshot(self, mock_run, mock_open_file, mock_exists):
        # Setup: simulate screenshot exists
        mock_exists.return_value = True
        
        mock_response = MagicMock()
        mock_response.returncode = 0
        mock_response.stdout = json.dumps({
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Found it!"}]
                    }
                }
            ]
        })
        mock_run.return_value = mock_response
        
        credentials = {"GEMINI_API_KEY": "test_gemini_key"}
        response = get_llm_response("gemini", credentials, "Look at this")
        
        self.assertEqual(response, "Found it!")
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        payload_str = args[args.index("-d") + 1]
        payload = json.loads(payload_str)
        
        # Verify base64 image data is passed to inlineData
        parts = payload["contents"][0]["parts"]
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertIn("data", parts[1]["inlineData"])

if __name__ == '__main__':
    unittest.main()
