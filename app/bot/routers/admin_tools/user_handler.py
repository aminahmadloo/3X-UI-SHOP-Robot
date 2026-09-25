"""Legacy module kept for import compatibility.

User management handlers live in user_management_handler.py.
"""
import logging

from aiogram import Router

logger = logging.getLogger(__name__)
router = Router(name=__name__)
