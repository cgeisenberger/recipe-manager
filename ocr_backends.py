"""
OCR Backend Abstraction
Supports Apple Vision (macOS) and Tesseract (cross-platform/Raspberry Pi)
"""

import json
import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TypedDict, Optional


class OCRResult(TypedDict):
    text: str
    confidence: float


# Maps ISO 639-1 codes (used in cookbook configs) to Tesseract language packs
_LANG_MAP = {
    "en": "eng",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "it": "ita",
    "nl": "nld",
    "pt": "por",
}


def iso_to_tesseract_lang(iso_code: str) -> str:
    """Convert ISO 639-1 language code to Tesseract language pack name."""
    return _LANG_MAP.get(iso_code.lower(), "eng")


class OCRBackend(ABC):
    @abstractmethod
    def extract(self, image_path: str) -> OCRResult:
        """Extract text from image. Returns dict with 'text' and 'confidence' (0–1)."""
        ...

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Return True if this backend can be used in the current environment."""
        ...

    @property
    def name(self) -> str:
        return type(self).__name__


class AppleVisionOCR(OCRBackend):
    """Apple Vision OCR via Swift subprocess. macOS only."""

    def __init__(self, swift_script_path: str = "./apple_ocr.swift"):
        self.swift_script = Path(swift_script_path)

    @classmethod
    def is_available(cls) -> bool:
        return platform.system() == "Darwin" and shutil.which("swift") is not None

    def extract(self, image_path: str) -> OCRResult:
        result = subprocess.run(
            ["swift", str(self.swift_script), image_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Apple Vision OCR failed: {result.stderr.strip()}")
        data = json.loads(result.stdout)
        return {"text": data["text"], "confidence": data["confidence"]}


class TesseractOCR(OCRBackend):
    """
    Tesseract OCR with Pillow preprocessing. Runs on Linux/macOS/Windows.
    Raspberry Pi setup: sudo apt install tesseract-ocr [tesseract-ocr-<lang>]
                        pip install pytesseract pillow
    """

    def __init__(self, lang: str = "eng"):
        """
        Args:
            lang: Tesseract language pack (e.g. 'eng', 'deu'). Use
                  iso_to_tesseract_lang() to convert from cookbook config codes.
        """
        self.lang = lang

    @classmethod
    def is_available(cls) -> bool:
        if shutil.which("tesseract") is None:
            return False
        try:
            import pytesseract  # noqa: F401
            return True
        except ImportError:
            return False

    def _preprocess(self, image_path: str):
        """
        Convert to grayscale and boost contrast/sharpness.
        Improves accuracy on cookbook photos with varied lighting.
        """
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(image_path).convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = img.filter(ImageFilter.SHARPEN)
        return img

    def extract(self, image_path: str) -> OCRResult:
        import pytesseract

        img = self._preprocess(image_path)

        # image_to_string preserves layout (paragraphs, columns)
        text = pytesseract.image_to_string(img, lang=self.lang)

        # image_to_data gives per-word confidence scores
        data = pytesseract.image_to_data(
            img, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        valid_confs = [int(c) for c in data["conf"] if int(c) != -1]
        confidence = sum(valid_confs) / len(valid_confs) / 100.0 if valid_confs else 0.0

        return {"text": text.strip(), "confidence": confidence}


def auto_detect_backend(
    swift_script_path: str = "./apple_ocr.swift",
    tesseract_lang: str = "eng",
) -> OCRBackend:
    """
    Return the best available OCR backend for the current platform.
    Prefers Apple Vision on macOS; falls back to Tesseract elsewhere.
    """
    if AppleVisionOCR.is_available():
        return AppleVisionOCR(swift_script_path)
    if TesseractOCR.is_available():
        return TesseractOCR(tesseract_lang)
    raise RuntimeError(
        "No OCR backend available.\n"
        "  macOS:        ensure Xcode command-line tools are installed\n"
        "  Linux/Pi:     sudo apt install tesseract-ocr && pip install pytesseract"
    )
