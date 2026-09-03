"""
utils/exceptions.py
 
Central custom exception hierarchy for SEO bot.
 
Expected failures (business-logic, recoverable) subclass SeoBotError directly
and are caught explicitly for fallback/retry. Unexpected errors (bugs, env)
are not mapped and bubble as UnhandledAutomationError for graceful top-level
logging without silent swallow of generic `except Exception`.
"""
 
from __future__ import annotations
 
 
class SeoBotError(Exception):
    """Base for all expected automation failures — never swallow as generic."""
 
    def __init__(self, message: str, *, engine: str | None = None, browser: str | None = None, keyword: str | None = None, url: str | None = None, cause: BaseException | None = None):
        super().__init__(message)
        self.engine = engine
        self.browser = browser
        self.keyword = keyword
        self.url = url
        self.cause = cause
 
 
class UnhandledAutomationError(SeoBotError):
    """Wrapper for truly unexpected errors — preserves traceback for alerting."""
    pass
 
 
# ── Config / Files ──────────────────────────────────────────────────────────
 
class ConfigError(SeoBotError):
    pass
 
 
class ConfigFileNotFoundError(ConfigError):
    pass
 
 
class ConfigInvalidError(ConfigError):
    pass
 
 
class ValidationError(ConfigError):
    pass
 
 
# ── Database ────────────────────────────────────────────────────────────────
 
class DatabaseError(SeoBotError):
    pass
 
 
class DatabaseUnavailableError(DatabaseError):
    pass
 
 
class DatabaseQueryError(DatabaseError):
    pass
 
 
# ── Browser ─────────────────────────────────────────────────────────────────
 
class BrowserError(SeoBotError):
    pass
 
 
class BrowserBinaryNotFoundError(BrowserError):
    pass
 
 
class UnsupportedBrowserError(BrowserError):
    pass
 
 
class BrowserStartupError(BrowserError):
    pass
 
 
class BrowserDiedError(BrowserError):
    pass
 
 
class BrowserNotAliveError(BrowserDiedError):
    pass
 
 
# ── Search Engine ───────────────────────────────────────────────────────────
 
class SearchEngineError(SeoBotError):
    pass
 
 
class EngineConfigError(SearchEngineError):
    pass
 
 
class InvalidLocatorError(EngineConfigError):
    pass
 
 
class EngineOpenError(SearchEngineError):
    pass
 
 
class SearchFailedError(SearchEngineError):
    pass
 
 
class CaptchaDetectedError(SearchEngineError):
    """CAPTCHA / verification page — retryable by switching engine."""
    pass
 
 
class VerificationError(CaptchaDetectedError):
    pass
 
 
class VideoTabOpenError(SearchEngineError):
    pass
 
 
class TargetNotFoundError(SearchEngineError):
    """Target website/video not found after exhausting pages/engines."""
    pass
 
 
class NextPageError(SearchEngineError):
    pass
 
 
# ── Network ─────────────────────────────────────────────────────────────────
 
class NetworkError(SeoBotError):
    pass
 
 
class NavigationError(NetworkError):
    pass
 
 
# ── YouTube ─────────────────────────────────────────────────────────────────
 
class YoutubeError(SeoBotError):
    pass
 
 
class YoutubeNetworkError(YoutubeError, NetworkError):
    pass
 
 
class VideoNotFoundError(YoutubeError, TargetNotFoundError):
    pass
 
 
class VideoCardsEmptyError(YoutubeError):
    pass
 
 
# ── Website ─────────────────────────────────────────────────────────────────
 
class WebsiteError(SeoBotError):
    pass
 
 
class WebsiteVisitError(WebsiteError):
    pass
 
 
# ── Session / Control ───────────────────────────────────────────────────────
 
class SessionError(SeoBotError):
    pass
 
 
class SessionInterruptedError(SessionError):
    pass
 
 
class LogWriteError(SeoBotError):
    pass
 
 
def wrap_unexpected(exc: BaseException, context: str = "") -> UnhandledAutomationError:
    """Wrap an unexpected exception so top-level can log it as bug, not business failure."""
    msg = f"Unexpected error{f' during {context}' if context else ''}: {exc}"
    return UnhandledAutomationError(msg, cause=exc)