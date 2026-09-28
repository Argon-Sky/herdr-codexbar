import json
import tempfile
import unittest
from pathlib import Path

from herdr_codexbar import harnesses


def codex_home(effort="medium"):
    home = Path(tempfile.mkdtemp())
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text(f'model_reasoning_effort = "{effort}"\n')
    return home


def transcript(records):
    path = Path(tempfile.mkdtemp()) / "rollout.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return str(path)


SESSION = {"type": "session_meta", "payload": {"model_provider": "openai"}}
TURN = {"type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "high"}}
USAGE = {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"total_tokens": 56_000}, "model_context_window": 400_000}}}
EMPTY_USAGE = {"type": "event_msg", "payload": {"type": "token_count", "info": None}}


class GrokAndCopilotTests(unittest.TestCase):
    def test_grok_status_line_payload(self):
        report = harnesses.grok({
            "model": {"id": "grok-4.5", "display_name": "Grok 4.5"},
            "effort": {"level": "low"},
            "context_window": {"context_window_size": 500_000, "context_tokens": 19_410, "session_input_tokens": 90_000, "used_percentage": 4},
        })
        self.assertEqual(report, {"harness": "grok", "provider_id": "grok", "model": "Grok 4.5", "effort": "low",
                                  "context_used": 19_410, "context_limit": 500_000, "context_percent": 4})

    def test_copilot_status_line_payload(self):
        report = harnesses.copilot({
            "model": {"id": "auto", "display_name": "Auto → gpt-5.6-luna"},
            "context_window": {"context_window_size": None, "used_percentage": None, "total_tokens": 15_722,
                               "current_context_tokens": 17_417, "displayed_context_limit": 200_000, "current_context_used_percentage": 9},
        })
        self.assertEqual(report, {"harness": "copilot", "provider_id": "github-copilot", "model": "Auto → gpt-5.6-luna", "effort": None,
                                  "context_used": 17_417, "context_limit": 200_000, "context_percent": 9})

    def test_missing_fields(self):
        for parser in (harnesses.grok, harnesses.copilot):
            report = parser({})
            self.assertEqual((report["model"], report["context_used"], report["context_percent"]), (None, None, None))


class ClaudeTests(unittest.TestCase):
    def test_status_line_payload(self):
        report = harnesses.claude({
            "model": {"display_name": "Opus 5.5"},
            "effort": {"level": "high"},
            "context_window": {"used_percentage": 12, "context_window_size": 1_000_000,
                               "current_usage": {"input_tokens": 10, "cache_creation_input_tokens": 1_000, "cache_read_input_tokens": 119_000}},
        })
        self.assertEqual(report, {"harness": "claude", "provider_id": "anthropic", "model": "Opus 5.5", "effort": "high",
                                  "context_used": 120_010, "context_limit": 1_000_000, "context_percent": 12})

    def test_missing_fields(self):
        report = harnesses.claude({})
        self.assertIsNone(report["context_used"])
        self.assertIsNone(report["model"])


class AntigravityTests(unittest.TestCase):
    def test_nominal_million_window(self):
        report = harnesses.antigravity({"model": {"id": "gemini-3-pro"}, "context_window": {"total_input_tokens": 250_000, "context_window_size": 1_048_576}})
        self.assertEqual(report["model"], "gemini-3-pro")
        self.assertEqual(report["context_percent"], 25)
        self.assertEqual(report["provider_id"], "antigravity")


class CodexTests(unittest.TestCase):
    def test_transcript_with_baseline(self):
        path = transcript([SESSION, TURN, USAGE, EMPTY_USAGE])
        report = harnesses.codex({"transcript_path": path}, codex_home())
        self.assertEqual(report["provider_id"], "openai")
        self.assertEqual((report["model"], report["effort"]), ("gpt-5.5", "high"))
        self.assertEqual(report["context_used"], 56_000)
        self.assertAlmostEqual(report["context_percent"], 44_000 / 388_000 * 100)

    def test_custom_provider_and_config_effort(self):
        path = transcript([{"type": "session_meta", "payload": {"model_provider": "ollama"}}, {"type": "turn_context", "payload": {"model": "qwen"}}])
        report = harnesses.codex({"transcript_path": path}, codex_home(effort="low"))
        self.assertEqual((report["provider_id"], report["effort"]), ("ollama", "low"))

    def test_long_transcript_is_read_backwards_across_chunks(self):
        filler = {"type": "response_item", "payload": {"text": "x" * 1_000}}
        path = transcript([SESSION, TURN, USAGE] + [filler] * 600)
        self.assertEqual(harnesses.codex({"transcript_path": path}, codex_home())["context_used"], 56_000)

    def test_missing_transcript(self):
        report = harnesses.codex({}, codex_home())
        self.assertEqual((report["provider_id"], report["model"], report["context_percent"]), ("openai", None, None))


if __name__ == "__main__":
    unittest.main()
