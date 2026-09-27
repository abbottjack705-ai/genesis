from __future__ import annotations

import json
import unittest
from pathlib import Path

from genesis.config import OperationalMode, dependency_lock_digest, load_config


class ConfigTests(unittest.TestCase):
    def test_default_config_is_pinned_and_offline(self):
        root = Path(__file__).resolve().parents[1]
        lock_digest = dependency_lock_digest(root / "requirements.lock")
        config = load_config(root / "config" / "defaults.json", lock_digest)
        self.assertEqual(config.mode, OperationalMode.OFFLINE_RESEARCH)
        self.assertFalse(config.live_enabled)
        self.assertEqual(config.max_bets_per_day, 0)

