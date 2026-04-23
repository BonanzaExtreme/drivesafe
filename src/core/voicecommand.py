"""
voicecommand.py – Voice Command Recognition using Vosk

Listens for voice commands and returns recognized actions.
Commands are fuzzy-matched against known patterns.
"""

from matplotlib import text
import pyaudio
import json
import time
from vosk import Model, KaldiRecognizer
import logging

logger = logging.getLogger(__name__)


class VoiceCommandRecognizer:
    """Recognizes voice commands using Vosk for offline speech recognition."""

    # Command keyword patterns → action name
    COMMAND_PATTERNS = {
        "open_archive": [
            "open archive",
            "open files",
            "open recordings",
            "open the archive",
            "open the files",
            "show archive",
            "show files",
            "view archive",
            "view files",
        ],
        "close_archive": [
            "close archive",
            "close files",
            "close file",
            "close the archive",
            "close the files",
        ],
        "open_settings": [
            "open settings",
            "open setting",
            "settings",
            "show settings",
        ],
        "close_settings": [
            "close settings",
            "close setting",
            "exit settings",
        ],
        "apply_settings": [
            "apply settings",
            "save settings",
            "confirm settings",
        ],
        "start_recording": [
            "start recording",
            "start record",
            "begin recording",
            "begin record",
            "recording on",
            
        ],
        "stop_recording": [
            "stop recording",
            "stop record",
            "end recording",
            "end record",
            "recording off",
            "stop",
            "pause recording",
        ],
        "mute_alerts": [
            "mute alerts",
            "mute audio",
            "silence",
            "quiet",
        ],
        "unmute_alerts": [
            "sound on",
            "enable audio",
        ],
        "set_voice_male": [
            "male voice",
            "set voice male",
            "voice male",
            "change voice male",
        ],
        "set_voice_female": [
            "female voice",
            "set voice female",
            "voice female",
            "change voice female",
        ],
    }

    def __init__(self, model_path: str, device_index: int = None, sample_rate: int = 16000):
        """
        Initialize voice recognizer.

        Args:
            model_path: Path to Vosk model directory (e.g. "models/vosk-model-small-en-us-0.15")
            device_index: Audio device index (None = default)
            sample_rate: Audio sample rate in Hz
        """
        self.sample_rate = sample_rate
        self.device_index = device_index
        self._last_command_time = 0
        self._last_recognized_text = ""
        self._debounce_time = 0.5  # Minimum time between command triggers (seconds)

        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, sample_rate)
            logger.info(f"✓ Vosk model loaded from {model_path}")
        except Exception as e:
            logger.error(f"✗ Failed to load Vosk model: {e}")
            self.model = None
            self.recognizer = None
            return

        # Open audio stream
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=4096,
            )
            logger.info(f"✓ Audio stream opened (device {device_index or 'default'})")
        except Exception as e:
            logger.error(f"✗ Failed to open audio stream: {e}")
            self.stream = None
            self.audio = None

    def recognize(self) -> dict:
        """
        Recognize a voice command. Non-blocking.

        Returns:
            {"action": "open_archive", "confidence": 0.95, "text": "open files"}
            or {"action": None, "confidence": 0.0, "text": ""} if no match
        """
        if not self.stream or not self.recognizer:
            return {"action": None, "confidence": 0.0, "text": ""}

        try:
            # Read audio chunk
            data = self.stream.read(4096, exception_on_overflow=False)

            # Feed to recognizer
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "")
            else:
                # Partial result
                partial = json.loads(self.recognizer.PartialResult())
                text = partial.get("partial", "")

            if text:
                return self._match_command(text)

        except Exception as e:
            logger.debug(f"Audio stream read error: {e}")

        return {"action": None, "confidence": 0.0, "text": ""}

    def _match_command(self, text: str) -> dict:
        """
        Match recognized text against known command patterns.
        
        Includes debounce to prevent duplicate command triggers from the same
        recognized phrase being emitted multiple times by the recognizer.

        Args:
            text: Recognized text from Vosk

        Returns:
            {"action": "open_archive", "confidence": 0.95, "text": "open files"}
            or {"action": None, ...} if debounce period is active
        """
        text_lower = text.lower().strip()
        logger.debug(f"[Voice] Received input: '{text}'")

        current_time = time.time()
        if (text_lower == self._last_recognized_text and 
            current_time - self._last_command_time < self._debounce_time):
            logger.debug(f"[Voice] ⊘ Duplicate command within debounce period, ignoring")
            return {"action": None, "confidence": 0.0, "text": text}

        best_action = None
        best_match_ratio = 0

        for action, patterns in self.COMMAND_PATTERNS.items():
            for pattern in patterns:
                if self._fuzzy_match(text_lower, pattern):
                    confidence = self._calculate_confidence(text_lower, pattern)
                    if confidence > best_match_ratio:
                        best_action = action
                        best_match_ratio = confidence

        if best_action:
            logger.info(f"[Voice] ✓ Matched command: '{best_action}' (confidence: {best_match_ratio:.1%})")
            # Update debounce state only on successful match
            self._last_recognized_text = text_lower
            self._last_command_time = current_time
        else:
            logger.debug(f"[Voice] ✗ No command matched for: '{text}'")

        return {
            "action": best_action,
            "confidence": best_match_ratio,
            "text": text,
        }

    @staticmethod
    def _fuzzy_match(text: str, pattern: str) -> bool:
        """
        Check if text contains or closely matches pattern.

        Simple fuzzy matching: checks if all words in pattern appear in text,
        or if pattern is a substring of text.
        """
        # Exact substring match
        if pattern in text:
            return True

        # Word-by-word match (more lenient)
        pattern_words = pattern.split()
        text_words = text.split()

        # All pattern words in text?
        if all(word in text for word in pattern_words):
            return True

        return False

    @staticmethod
    def _calculate_confidence(text: str, pattern: str) -> float:
        """
        Calculate confidence score (0-1) based on match quality.

        Higher score for exact matches, lower for fuzzy matches.
        """
        text_lower = text.lower()
        pattern_lower = pattern.lower()

        # Exact match
        if text_lower == pattern_lower:
            return 1.0

        # Substring match
        if pattern_lower in text_lower:
            return 0.95

        # Word overlap
        text_words = set(text_lower.split())
        pattern_words = set(pattern_lower.split())
        if pattern_words and text_words:
            overlap = len(pattern_words & text_words) / len(pattern_words)
            return min(0.9, overlap * 0.9)

        return 0.5

    def close(self):
        """Clean up audio resources."""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.audio:
            self.audio.terminate()
        logger.info("✓ Voice recognizer closed")


# Standalone usage
if __name__ == "__main__":
    import time

    recognizer = VoiceCommandRecognizer("models/vosk-model-small-en-us-0.15")

    print("Listening for voice commands (10 seconds)...")
    start = time.time()

    while time.time() - start < 10:
        result = recognizer.recognize()
        
        if result["action"]:
            print(f"✓ Command: {result['action']} ({result['confidence']:.2%})")
            print(f"  Text: '{result['text']}'")
        time.sleep(0.1)

    recognizer.close()