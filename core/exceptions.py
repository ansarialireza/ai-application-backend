class ServiceError(Exception):
    code = "service_error"
    status_code = 502
    retryable = False
