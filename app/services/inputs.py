"""Bound HTTP identifiers before conversion or database access."""
from flask import request
from app.services.errors import DomainError


def positive_integer(value, label, maximum=2_147_483_647):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > len(str(maximum))):
        raise DomainError('INVALID_INPUT', f'{label}須為1至{maximum}的整數', 400)
    number = int(value)
    if not 1 <= number <= maximum:
        raise DomainError('INVALID_INPUT', f'{label}須為1至{maximum}的整數', 400)
    return number


def query_integer(name, label, default=None, maximum=2_147_483_647):
    values = request.args.getlist(name)
    if not values:
        return default
    if len(values) != 1:
        raise DomainError('INVALID_INPUT', f'{label}不得重複指定', 400)
    return positive_integer(values[0], label, maximum)
