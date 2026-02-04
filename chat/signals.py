import os
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from .models import MessageFile, UserProfile

@receiver(post_delete, sender=MessageFile)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem when corresponding `MessageFile` object is deleted.
    """
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)

@receiver(post_delete, sender=UserProfile)
def auto_delete_profile_pic_on_delete(sender, instance, **kwargs):
    """
    Deletes profile pic from filesystem when corresponding `UserProfile` object is deleted.
    """
    if instance.profile_pic:
        if os.path.isfile(instance.profile_pic.path):
            os.remove(instance.profile_pic.path)

@receiver(pre_save, sender=UserProfile)
def auto_delete_old_profile_pic_on_change(sender, instance, **kwargs):
    """
    Deletes old profile pic from filesystem when corresponding `UserProfile` object is updated
    with a new profile pic.
    """
    if not instance.pk:
        return False

    try:
        old_profile = UserProfile.objects.get(pk=instance.pk)
    except UserProfile.DoesNotExist:
        return False

    new_pic = instance.profile_pic
    old_pic = old_profile.profile_pic

    if old_pic and old_pic != new_pic:
        if os.path.isfile(old_pic.path):
            os.remove(old_pic.path)
