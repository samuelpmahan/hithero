"""The shared rate limiter. app.py attaches it to the app; routers decorate with it."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
