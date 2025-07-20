from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar

T = TypeVar("T")
T2 = TypeVar("T2")
E = TypeVar("E")
E2 = TypeVar("E2")


class UnwrapError(Exception):
    def __init__(self, message: str, *args, **kwargs):
        super().__init__(message, *args, **kwargs)


class Result(ABC, Generic[T, E]):
    @abstractmethod
    def is_ok(self) -> bool: ...

    @abstractmethod
    def is_err(self) -> bool: ...

    @abstractmethod
    def unwrap(self) -> T: ...

    @abstractmethod
    def unwrap_or(self, default: T) -> T: ...

    @abstractmethod
    def unwrap_or_else(self, op: Callable[[E], T]) -> T: ...

    @abstractmethod
    def map(self, func: Callable[[T], T2]) -> "Result[T2, E]": ...

    @abstractmethod
    def map_err(self, func: Callable[[E], E2]) -> "Result[T, E2]": ...

    @abstractmethod
    def and_then(self, func: Callable[[T], "Result[T2, E]"]) -> "Result[T2, E]": ...

    @abstractmethod
    def expect(self, message: str) -> T: ...


@dataclass(frozen=True, slots=True)
class Ok(Result[T, E]):
    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self.value

    def unwrap_or(self, default: T) -> T:
        return self.value

    def unwrap_or_else(self, op: Callable[[E], T]) -> T:
        return self.value

    def expect(self, message: str) -> T:
        return self.value

    def map(self, func: Callable[[T], T2]) -> "Ok[T2, E]":
        return Ok(func(self.value))

    def map_err(self, func: Callable[[E], E2]) -> "Ok[T, E2]":
        return Ok(self.value)

    def and_then(self, func: Callable[[T], "Result[T2, E]"]) -> "Result[T2, E]":
        return func(self.value)

    def __repr__(self):
        return f"Ok({self.value})"

    def __str__(self):
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Err(Result[T, E]):
    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> T:
        if isinstance(self.error, Exception):
            raise self.error
        raise UnwrapError(str(self.error))

    def unwrap_or(self, default: T) -> T:
        return default

    def unwrap_or_else(self, op: Callable[[E], T]) -> T:
        return op(self.error)

    def expect(self, message: str) -> T:
        raise UnwrapError(message)

    def map(self, func: Callable[[T], T2]) -> "Err[T2, E]":
        return Err(self.error)

    def map_err(self, func: Callable[[E], E2]) -> "Err[T, E2]":
        return Err(func(self.error))

    def and_then(self, func: Callable[[T], "Result[T2, E]"]) -> "Err[T2, E]":
        return Err(self.error)

    def __repr__(self):
        return f"Err({self.error})"

    def __str__(self):
        return str(self.error)


@dataclass(frozen=True, slots=True)
class Option(Generic[T]):
    _value: Optional[T]

    def is_some(self) -> bool:
        return self._value is not None

    def is_none(self) -> bool:
        return self._value is None

    def unwrap(self) -> T:
        if self.is_none():
            raise UnwrapError("Tried to unwrap None Option")
        return self._value  # type: ignore

    def unwrap_or(self, default: T) -> T:
        return self._value if self._value is not None else default

    def unwrap_or_else(self, op: Callable[[], T]) -> T:
        return self._value if self._value is not None else op()

    def unwrap_or_none(self) -> Optional[T]:
        return self._value if self._value is not None else None

    def expect(self, message: str) -> T:
        if self._value is None:
            raise UnwrapError(message)
        return self._value

    def map(self, func: Callable[[T], T2]) -> "Option[T2]":
        if self.is_some():
            return Option(func(self._value))  # type: ignore
        return Option(None)

    def and_then(self, func: Callable[[T], "Option[T2]"]) -> "Option[T2]":
        if self.is_some():
            return func(self._value)  # type: ignore
        return Option(None)

    def __repr__(self):
        return f"Some({self._value})" if self.is_some() else "None"

    def __str__(self):
        return str(self._value)


def some(value):
    return Option(value)


def none():
    return Option(None)


if __name__ == "__main__":
    # --- Option Tests ---
    opt = some(10)
    assert opt.is_some()
    assert opt.unwrap() == 10
    assert opt.map(lambda x: x * 2).unwrap() == 20
    assert opt.and_then(lambda x: some(x * 3)).unwrap() == 30
    assert none().is_none()
    assert none().unwrap_or(42) == 42

    # --- Result Tests ---
    ok_result = Ok(5)
    assert ok_result.is_ok()
    assert ok_result.unwrap() == 5
    assert ok_result.map(lambda x: x + 1).unwrap() == 6
    assert ok_result.and_then(lambda x: Ok(x * 2)).unwrap() == 10

    err_result = Err("fail")
    assert err_result.is_err()
    assert err_result.unwrap_or(123) == 123
    assert err_result.map(lambda x: x * 10).is_err()
    assert err_result.map_err(lambda e: e.upper()).error == "FAIL"

    # --- Exception Test ---
    try:
        none().unwrap()
    except UnwrapError:
        print("Correctly raised UnwrapError on Option unwrap of None.")

    try:
        Err("fail").unwrap()
    except UnwrapError:
        print("Correctly raised UnwrapError on Err unwrap.")

    print("All tests passed.")
