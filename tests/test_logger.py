import json
import logging
from app.main import JSONFormatter

def test_json_formatter_extra():
    formatter = JSONFormatter()
    
    # Create a log record with extra fields
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    # Add extra fields like how logger.info("...", extra={...}) works
    record.__dict__["request_id"] = "req-123"
    record.__dict__["user_id"] = "user-123"
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    assert parsed["message"] == "Test message"
    assert parsed["request_id"] == "req-123"
    assert parsed["user_id"] == "user-123"
    assert "time" in parsed
    assert "level" in parsed
