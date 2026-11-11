import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import load_local_env


class ConfigTests(unittest.TestCase):
    def test_dotenv_is_loaded_from_project_root_and_shell_variables_win(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("AI_MODEL=file-model\nAI_SERVICE_TOKEN=file-token\n", encoding="utf-8")
            with patch("backend.config.__file__", str(root / "backend" / "config.py")), patch.dict(os.environ, {"AI_MODEL": "shell-model"}, clear=True):
                load_local_env()
                self.assertEqual(os.environ["AI_MODEL"], "shell-model")
                self.assertEqual(os.environ["AI_SERVICE_TOKEN"], "file-token")
