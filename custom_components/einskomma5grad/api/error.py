class ApiError(Exception):
    """Base class for all API related errors"""



class AuthenticationError(ApiError):
    """Raised when there is an authentication error"""

    def __init__(self, message="Authentication failed"):
        self.message = message
        super().__init__(self.message)


class InvalidCredentialsError(AuthenticationError):
    """Raised when the login rejects the stored username or password"""

    def __init__(self, message="Invalid credentials"):
        super().__init__(message)


class RequestError(ApiError):
    """Raised when there is an error making a request"""

    def __init__(self, message="Request failed"):
        self.message = message
        super().__init__(self.message)
