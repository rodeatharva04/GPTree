"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# Force migrations on startup for Render execution
try:
    print("WSGI Startup: Running migrations...")
    call_command('migrate')
    print("WSGI Startup: Creating default admin...")
    call_command('create_default_admin')
except Exception as e:
    print(f"WSGI Startup Error: {e}")
