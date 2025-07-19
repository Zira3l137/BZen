class InvalidFileException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class InvalidGameDirectoryException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
