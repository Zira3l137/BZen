class InvalidFileException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class InvalidGameDirectoryException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class VobHasNoMeshException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class NoVisualDataException(Exception):
    def __init__(self, message: str):
        super().__init__(message)


class UnknownExtensionException(Exception):
    def __init__(self, message: str):
        super().__init__(message)
