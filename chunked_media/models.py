from __future__ import unicode_literals

import mimetypes
import os.path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import Signal
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils.translation import ugettext_lazy as translate_text

from taggit.managers import TaggableManager
from wagtail import VERSION as WAGTAIL_VERSION
from wagtail.core.models import CollectionMember
from wagtail.search import index
from wagtail.search.queryset import SearchableQuerySetMixin

if WAGTAIL_VERSION < (2, 9):
    from wagtail.admin.utils import get_object_usage
else:
    from wagtail.admin.models import get_object_usage


# Python 2.x compability apis are removed from Django 3
# https://docs.djangoproject.com/en/3.0/releases/3.0/#removed-private-python-2-compatibility-apis
try:
    from django.utils.encoding import python_2_unicode_compatible
except ImportError:
    def python_2_unicode_compatible(x):
        return x


class MediaQuerySet(SearchableQuerySetMixin, models.QuerySet):
    pass


@python_2_unicode_compatible
class AbstractMedia(CollectionMember, index.Indexed, models.Model):
    MEDIA_TYPES = (
        ('audio', translate_text('Audio file')),
        ('video', translate_text('Video file')),
    )

    title = models.CharField(max_length=255, verbose_name=translate_text('title'))
    file = models.FileField(upload_to='media', verbose_name=translate_text('file'))

    type = models.CharField(choices=MEDIA_TYPES, max_length=255, blank=False, null=False)
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name=translate_text('width'))
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name=translate_text('height'))
    thumbnail = models.FileField(upload_to='media_thumbnails', blank=True, verbose_name=translate_text('thumbnail'))

    created_at = models.DateTimeField(verbose_name=translate_text('created at'), auto_now_add=True)
    uploaded_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=translate_text('uploaded by user'),
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL
    )

    tags = TaggableManager(help_text=None, blank=True, verbose_name=translate_text('tags'))

    objects = MediaQuerySet.as_manager()

    search_fields = CollectionMember.search_fields + [
        index.SearchField('title', partial_match=True, boost=10),
        index.RelatedFields('tags', [
            index.SearchField('name', partial_match=True, boost=10),
        ]),
        index.FilterField('uploaded_by_user'),
    ]

    def __str__(self):
        return self.title

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def thumbnail_filename(self):
        return os.path.basename(self.thumbnail.name)

    @property
    def file_extension(self):
        return os.path.splitext(self.filename)[1][1:]

    @property
    def url(self):
        #TODO: Implement aiohttp here to await the file.url object as a monad
        return self.file.url

    @property
    def sources(self):
        return [{
            'src': self.url or reverse('chunked_media:index'),
            'type': mimetypes.guess_type(self.filename)[0] or 'application/octet-stream',
        }]

    def get_usage(self):
        return get_object_usage(self)

    @property
    def usage_url(self):
        return reverse('chunked_media:media_usage',
                       args=(self.id,))

    def is_editable_by_user(self, user):
        from chunked_media.permissions import permission_policy
        return permission_policy.user_has_permission_for_instance(user, 'change', self)

    class Meta:
        abstract = True
        verbose_name = translate_text('media')


class Media(AbstractMedia):
    admin_form_fields = (
        'title',
        'file',
        'collection',
        'width',
        'height',
        'thumbnail',
        'tags',
    )

def get_media_model():
    from django.conf import settings
    from django.apps import apps

    try:
        app_label, model_name = settings.CHUNKED_MEDIA_MODEL.split('.')
    except AttributeError:
        return Media
    except ValueError:
        raise ImproperlyConfigured("CHUNKED_MEDIA_MODEL must be of the form 'app_label.model_name'")

    media_model = apps.get_model(app_label, model_name)
    if media_model is None:
        raise ImproperlyConfigured(
            "CHUNKED_MEDIA_MODEL refers to model '%s' that has not been installed" %
            settings.CHUNKED_MEDIA_MODEL
        )
    return media_model


# Receive the pre_delete signal and delete the file associated with the model instance.
@receiver(pre_delete, sender=Media)
def media_delete(sender, instance, **kwargs):
    # Pass false so FileField doesn't save the model.
    instance.file.delete(False)
    instance.thumbnail.delete(False)


media_served = Signal(providing_args=['request'])
