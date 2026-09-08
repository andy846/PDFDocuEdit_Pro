"""Shared, deliberately limited OCR language contract."""

OCR_LANGUAGE = "chi_tra+eng"
OCR_LANGUAGE_OPTIONS = (
    ("Traditional Chinese + English", OCR_LANGUAGE),
    ("Traditional Chinese", "chi_tra"),
    ("English", "eng"),
)


def normalize_ocr_language(language: str) -> str:
    """Accept supported languages and canonicalize the mixed-language alias."""
    if language == "eng+chi_tra":
        return OCR_LANGUAGE
    if language in {value for _, value in OCR_LANGUAGE_OPTIONS}:
        return language
    raise ValueError(f"Unsupported OCR language: {language}")
