from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Creates a default superuser if it does not exist'

    def handle(self, *args, **options):
        username = os.environ.get('DEFAULT_ADMIN_USER', 'rodeatharva')
        password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'pizzapizza')
        email = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')

        if not User.objects.filter(username=username).exists():
            print(f"Creating superuser: {username}")
            User.objects.create_superuser(username, email, password)
            print("Superuser created successfully.")
        else:
            print(f"Superuser {username} already exists.")
