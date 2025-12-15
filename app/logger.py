import logging
import json
from logging.handlers import RotatingFileHandler

def setup_logger():
    """
    Sets up a logger to output structured JSON logs to a rotating file.
    """
    logger = logging.getLogger("report_logger")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Prevent logs from being duplicated by the root logger

    # Use a rotating file handler to prevent the log file from growing indefinitely
    handler = RotatingFileHandler("report_history.log", maxBytes=10485760, backupCount=5) # 10MB per file

    # Define a custom JSON format
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_object = {
                "timestamp": self.formatTime(record, self.datefmt),
                "level": record.levelname,
            }
            # If the message is a dictionary, merge it into the log object
            if isinstance(record.msg, dict):
                log_object.update(record.msg)
            else:
                log_object["message"] = record.getMessage()

            return json.dumps(log_object)

    formatter = JsonFormatter()
    handler.setFormatter(formatter)

    # Avoid adding handlers multiple times
    if not logger.handlers:
        logger.addHandler(handler)

    return logger

# Initialize and export the logger
report_logger = setup_logger()