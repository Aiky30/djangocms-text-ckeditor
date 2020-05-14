# -*- coding: utf-8 -*-
import copy
import json
import re
import unittest

from django.contrib import admin
from django.contrib.auth import get_permission_codename
from django.contrib.auth.models import Permission
from django.template import RequestContext
from django.utils.encoding import force_text
from django.utils.html import escape
from django.utils.http import urlencode, urlunquote

from cms.api import add_plugin, create_page, create_title
from cms.models import CMSPlugin, Page
from cms.utils.urlutils import admin_reverse

from djangocms_text_ckeditor.cms_plugins import TextPlugin
from djangocms_text_ckeditor.models import Text
from djangocms_text_ckeditor.utils import (
    _plugin_tags_to_html, _render_cms_plugin, plugin_tags_to_admin_html,
    plugin_tags_to_id_list, plugin_to_tag,
)

from .base import BaseTestCase


try:
    from djangocms_transfer.exporter import export_page
    HAS_DJANGOCMS_TRANSFER = True
except ImportError:
    HAS_DJANGOCMS_TRANSFER = False

try:
    import djangocms_translations  # noqa
    HAS_DJANGOCMS_TRANSLATIONS = True
except ImportError:
    HAS_DJANGOCMS_TRANSLATIONS = False


class PluginActionsTestCase(BaseTestCase):

    def get_custom_admin_url(self, plugin_class, name):
        plugin_type = plugin_class.__name__.lower()
        url_name = "%s_%s_%s" % (plugin_class.model._meta.app_label, plugin_type, name)
        return admin_reverse(url_name)

    def _add_child_plugin(self, text_plugin, plugin_type='PicturePlugin', data_suffix=None):
        name = '{} record'.format(plugin_type)

        if data_suffix is not None:
            name = '{} {}'.format(name, data_suffix)

        basic_plugins = {
            'LinkPlugin': {
                'name': name,
                'external_link': 'https://www.django-cms.org',
            },
            'PreviewDisabledPlugin': {},
            'SekizaiPlugin': {},
        }

        if plugin_type == 'PicturePlugin':
            data = {'caption_text': name, 'picture': self.create_filer_image_object()}
        else:
            data = basic_plugins[plugin_type]

        plugin = add_plugin(
            text_plugin.placeholder,
            plugin_type,
            'en',
            target=text_plugin,
            **data
        )
        return plugin

    def _add_text_plugin(self, placeholder, plugin_type="TextPlugin"):
        text_plugin = add_plugin(
            placeholder,
            plugin_type,
            "en",
            body="Hello World",
        )
        return text_plugin

    def _replace_plugin_contents(self, text, new_plugin_content):
        def _do_replace(obj, match):
            return plugin_to_tag(obj, content=new_plugin_content)
        return _plugin_tags_to_html(text, output_func=_do_replace)

    def add_plugin_to_text(self, text_plugin, plugin):
        text_plugin.body = '%s %s' % (text_plugin.body, plugin_to_tag(plugin))
        text_plugin.save()
        return text_plugin

    def _give_permission(self, user, model, permission_type, save=True):
        codename = get_permission_codename(permission_type, model._meta)
        user.user_permissions.add(Permission.objects.get(codename=codename))

    def _give_cms_permissions(self, user):
        for perm_type in ['add', 'change', 'delete']:
            for model in [Page]:
                self._give_permission(user, model, perm_type)

    def get_page_admin(self):
        admin.autodiscover()
        return admin.site._registry[Page]

    def get_post_request(self, data):
        return self.get_request(post_data=data)

    def get_plugin_id_from_response(self, response):
        url = urlunquote(response.url)
        # Ideal case, this looks like:
        # /en/admin/cms/page/edit-plugin/1/
        return re.findall('\d+', url)[0]  # noqa

    def test_add_and_edit_plugin(self):
        """
        Test that you can add a text plugin
        """
        admin = self.get_superuser()
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        endpoint = self.get_add_plugin_uri(simple_placeholder, 'TextPlugin')

        with self.login_user_context(admin):
            response = self.client.get(endpoint)

        text_plugin_pk = self.get_plugin_id_from_response(response)

        self.assertIn('?delete-on-cancel', response.url)
        self.assertEqual(response.status_code, 302)

        # Assert "ghost" plugin has been created
        self.assertObjectExist(CMSPlugin.objects.all(), pk=text_plugin_pk)

        cms_plugin = CMSPlugin.objects.get(pk=text_plugin_pk)
        text_plugin_class = cms_plugin.get_plugin_class_instance()

        # Assert "real" plugin has not been created yet
        self.assertObjectDoesNotExist(Text.objects.all(), pk=text_plugin_pk)

        add_url = response.url

        with self.login_user_context(admin):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, cms_plugin)
            response = self.client.get(add_url)

            self.assertEqual(response.status_code, 200)

            # Assert cancel token is present
            self.assertContains(response, action_token)

        with self.login_user_context(admin):
            data = {'body': "Hello world"}
            response = self.client.post(add_url, data)

        self.assertEqual(response.status_code, 200)

        # Assert "real" plugin has been created yet
        self.assertObjectExist(Text.objects.all(), pk=text_plugin_pk)

        text_plugin = Text.objects.get(pk=text_plugin_pk)

        # Assert the text was correctly saved
        self.assertEqual(text_plugin.body, "Hello world")

    def test_add_and_cancel_plugin(self):
        """
        Test that you can add a text plugin
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        endpoint = self.get_add_plugin_uri(simple_placeholder, 'TextPlugin')

        with self.login_user_context(self.get_superuser()):
            response = self.client.get(endpoint)

        self.assertEqual(response.status_code, 302)

        # Point to the newly created text plugin
        text_plugin_pk = self.get_plugin_id_from_response(response)
        cms_plugin = CMSPlugin.objects.get(pk=text_plugin_pk)
        text_plugin_class = cms_plugin.get_plugin_class_instance()

        # Assert "ghost" plugin has been created
        self.assertObjectExist(CMSPlugin.objects.all(), pk=text_plugin_pk)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, cms_plugin)
            data = {'token': action_token}
            request = self.get_post_request(data)
            response = text_plugin_class.delete_on_cancel(request)
            self.assertEqual(response.status_code, 204)

        # Assert "ghost" plugin has been removed
        self.assertObjectDoesNotExist(CMSPlugin.objects.all(), pk=text_plugin_pk)

        # Assert "real" plugin was never created
        self.assertObjectDoesNotExist(Text.objects.all(), pk=text_plugin_pk)

        # Assert user can't delete a non "ghost" plugin
        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            data = {'token': action_token}
            request = self.get_post_request(data)
            response = text_plugin_class.delete_on_cancel(request)
            self.assertEqual(response.status_code, 400)

    def test_add_and_cancel_child_plugin(self):
        """
        Test that you can add a text plugin
        """
        admin = self.get_superuser()
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )

        text_plugin_class = text_plugin.get_plugin_class_instance()

        child_plugin_1 = add_plugin(
            simple_placeholder,
            'PicturePlugin',
            'en',
            target=text_plugin,
            picture=self.create_filer_image_object(),
            caption_text="Foo",
        )
        child_plugin_2 = add_plugin(
            simple_placeholder,
            'PicturePlugin',
            'en',
            target=text_plugin,
            picture=self.create_filer_image_object(),
            caption_text="Foo",
        )
        child_plugin_3 = add_plugin(
            simple_placeholder,
            'PicturePlugin',
            'en',
            target=text_plugin,
            picture=self.create_filer_image_object(),
            caption_text="Foo",
        )
        child_plugin_4 = add_plugin(
            simple_placeholder,
            'PicturePlugin',
            'en',
            target=text_plugin,
            picture=self.create_filer_image_object(),
            caption_text="Foo",
        )

        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin_1)
        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin_4)

        with self.login_user_context(admin):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)

            # Assert user is unable to delete a saved child plugin
            data = {'token': action_token, 'child_plugins': [child_plugin_1.pk]}
            request = self.get_post_request(data)
            response = text_plugin_class.delete_on_cancel(request)
            self.assertEqual(response.status_code, 400)
            self.assertObjectExist(CMSPlugin.objects.all(), pk=child_plugin_1.pk)

            # Assert user is unable to delete if plugins array contains
            # an unsaved plugin.
            plugin_ids = [
                child_plugin_1.pk,
                child_plugin_2.pk,
                child_plugin_3.pk,
                child_plugin_4.pk,
            ]
            data = {'token': action_token, 'child_plugins': plugin_ids}
            request = self.get_post_request(data)
            response = text_plugin_class.delete_on_cancel(request)
            self.assertEqual(response.status_code, 400)
            self.assertObjectExist(CMSPlugin.objects.all(), pk=child_plugin_1.pk)
            self.assertObjectExist(CMSPlugin.objects.all(), pk=child_plugin_2.pk)
            self.assertObjectExist(CMSPlugin.objects.all(), pk=child_plugin_3.pk)
            self.assertObjectExist(CMSPlugin.objects.all(), pk=child_plugin_4.pk)

            plugin_ids = [
                child_plugin_2.pk,
                child_plugin_3.pk,
            ]
            data = {'token': action_token, 'child_plugins': plugin_ids}
            request = self.get_post_request(data)
            response = text_plugin_class.delete_on_cancel(request)
            self.assertEqual(response.status_code, 204)

            self.assertObjectDoesNotExist(CMSPlugin.objects.all(), pk=child_plugin_2.pk)
            self.assertObjectDoesNotExist(CMSPlugin.objects.all(), pk=child_plugin_3.pk)

    def test_action_token_per_session(self):
        # Assert that a cancel token for the same plugin
        # is different per user session.
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )

        text_plugin_class = text_plugin.get_plugin_class_instance()

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token_1 = text_plugin_class.get_action_token(request, text_plugin)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token_2 = text_plugin_class.get_action_token(request, text_plugin)

        self.assertNotEqual(action_token_1, action_token_2)

    def test_add_and_cancel_plugin_permissions(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        endpoint = self.get_add_plugin_uri(simple_placeholder, 'TextPlugin')

        with self.login_user_context(self.user):
            response = self.client.post(endpoint, {})
            self.assertEqual(response.status_code, 302)

        # Point to the newly created text plugin
        text_plugin_pk = self.get_plugin_id_from_response(response)
        cms_plugin = CMSPlugin.objects.get(pk=text_plugin_pk)
        text_plugin_class = cms_plugin.get_plugin_class_instance()

        endpoint = self.get_custom_admin_url(TextPlugin, 'delete_on_cancel')

        # Assert a standard user (no staff) can't delete ghost plugin
        with self.login_user_context(self.get_standard_user()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, cms_plugin)
            data = {'token': action_token}
            response = self.client.post(endpoint, data)
            self.assertEqual(response.status_code, 403)

        staff_user = self._create_user("addonly-staff", is_staff=True, is_superuser=False)

        self._give_cms_permissions(staff_user)
        self._give_permission(staff_user, text_plugin_class.model, 'add')

        with self.login_user_context(staff_user):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, cms_plugin)
            data = {'token': action_token}
            response = self.client.post(endpoint, data)
            self.assertEqual(response.status_code, 204)

    def test_change_form_has_rendered_plugin_content(self):
        """
        When the text form is rendered in the admin,
        the child plugins are rendered as their contents passed
        as initial data to the text field.
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )

        child_plugins = [
            self._add_child_plugin(text_plugin),
            self._add_child_plugin(text_plugin),
        ]

        for plugin in child_plugins:
            text_plugin = self.add_plugin_to_text(text_plugin, plugin)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            context = RequestContext(request)
            context['request'] = request
            text_with_rendered_plugins = plugin_tags_to_admin_html(
                text=text_plugin.body,
                context=context,
            )

            endpoint = self.get_change_plugin_uri(text_plugin)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.context['adminform'].form['body'].value(),
                text_with_rendered_plugins,
            )
            self.assertContains(
                response,
                escape(text_with_rendered_plugins),
                html=False,
            )

    def test_user_cant_edit_child_plugins_directly(self):
        """
        No user regardless of permissions can modify the contents
        of a child plugin directly in the text plugin text.
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )

        child_plugins = [
            self._add_child_plugin(text_plugin),
            self._add_child_plugin(text_plugin),
        ]

        for plugin in child_plugins:
            text_plugin = self.add_plugin_to_text(text_plugin, plugin)

        with self.login_user_context(self.get_superuser()):
            expected_text = text_plugin.body

            # This returns the child plugins with their content
            # overridden to <img src="">
            overridden_text = self._replace_plugin_contents(
                text_plugin.body,
                new_plugin_content='<img src="">',
            )

            endpoint = self.get_change_plugin_uri(text_plugin)
            response = self.client.post(endpoint, {'body': overridden_text})
            text_plugin.refresh_from_db()

            self.assertEqual(response.status_code, 200)
            self.assertXMLEqual(text_plugin.body, expected_text)

    def test_render_child_plugin_endpoint(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )
        text_plugin_class = text_plugin.get_plugin_class_instance()
        child_plugin = self._add_child_plugin(text_plugin)
        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)

            context = RequestContext(request)
            context['request'] = request
            rendered_content = _render_cms_plugin(child_plugin, context)
            rendered_child_plugin = plugin_to_tag(
                child_plugin,
                content=rendered_content,
                admin=True,
            )

            self.assertEqual(force_text(response.content), rendered_child_plugin)

        child_plugin = self._add_child_plugin(text_plugin, plugin_type='PreviewDisabledPlugin')
        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)

            # it is important that we do not add any extra whitespace inside of
            # <cms-plugin></cms-plugin>
            rendered_child_plugin = ('<cms-plugin render-plugin=false '
                                     'alt="Preview Disabled Plugin - 3 '
                                     '"title="Preview Disabled Plugin - 3" '
                                     'id="3"><span>Preview is disabled for this plugin</span>'
                                     '</cms-plugin>')

            self.assertEqual(force_text(response.content), rendered_child_plugin)

    def test_render_child_plugin_endpoint_calls_context_processors(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )
        text_plugin_class = text_plugin.get_plugin_class_instance()
        child_plugin = self._add_child_plugin(
            text_plugin,
            plugin_type='SekizaiPlugin',
        )
        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin)

        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 200)

            context = RequestContext(request)
            context['request'] = request
            rendered_content = _render_cms_plugin(child_plugin, context)
            rendered_child_plugin = plugin_to_tag(
                child_plugin,
                content=rendered_content,
                admin=True,
            )

            self.assertEqual(force_text(response.content), rendered_child_plugin)

    def test_render_child_plugin_permissions(self):
        """
        Users can't render a child plugin without change permissions
        on the placeholder attached object and the text plugin.
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )
        text_plugin_class = text_plugin.get_plugin_class_instance()
        child_plugin = self._add_child_plugin(text_plugin)
        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin)

        with self.login_user_context(self.get_standard_user()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 403)
            self.assertEqual(force_text(response.content), '<h1>403 Forbidden</h1>')

    def test_render_child_plugin_token_validation(self):
        """
        Users can only render a child plugin if the token
        was created in the current session and it's text plugin
        matches the child plugin parent.
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the first",
        )
        text_plugin_class = text_plugin.get_plugin_class_instance()
        child_plugin = self._add_child_plugin(text_plugin)

        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin)

        # Tokens are unique per session.
        # Users can't render a child plugin with a token
        # from another session.
        with self.login_user_context(self.get_superuser()):
            request = self.get_request()

        with self.login_user_context(self.get_superuser()):
            action_token = text_plugin_class.get_action_token(request, text_plugin)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 400)
            self.assertEqual(force_text(response.content), 'Unable to process your request. Invalid token.')

        text_plugin_2 = add_plugin(
            simple_placeholder,
            "TextPlugin",
            "en",
            body="I'm the second",
        )

        # Tokens are unique per text plugin.
        # User can't render a child plugin for a token whose text plugin
        # does not match the plugin's parent.
        with self.login_user_context(self.get_superuser()):
            request = self.get_request()
            action_token = text_plugin_class.get_action_token(request, text_plugin_2)
            endpoint = self.get_custom_admin_url(TextPlugin, 'render_plugin')
            endpoint += '?token={}&plugin={}'.format(action_token, child_plugin.pk)
            response = self.client.get(endpoint)

            self.assertEqual(response.status_code, 400)
            self.assertEqual(force_text(response.content), 'Unable to process your request.')

    def test_render_plugin(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = self._add_text_plugin(simple_placeholder)

        for i in range(0, 10):
            plugin = self._add_child_plugin(
                text_plugin,
                plugin_type='LinkPlugin',
                data_suffix=i
            )

            text_plugin = self.add_plugin_to_text(text_plugin, plugin)

        with self.assertNumQueries(2):
            request = self.get_request()
            context = RequestContext(request)
            context['request'] = request
            rendered = _render_cms_plugin(text_plugin, context)

        for i in range(0, 10):
            self.assertTrue('LinkPlugin record %d' % i in rendered)

    def test_render_extended_plugin(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')
        text_plugin = self._add_text_plugin(simple_placeholder, 'ExtendedTextPlugin')

        for i in range(0, 10):
            plugin = self._add_child_plugin(
                text_plugin,
                plugin_type='LinkPlugin',
                data_suffix=i
            )

            text_plugin = self.add_plugin_to_text(text_plugin, plugin)

        with self.assertNumQueries(2):
            request = self.get_request()
            context = RequestContext(request)
            context['request'] = request
            rendered = _render_cms_plugin(text_plugin, context)

        for i in range(0, 10):
            self.assertTrue('LinkPlugin record %d' % i in rendered)

    def test_copy_plugin_integrity(self):
        """
        Test that copying of textplugins replaces references to copied plugins
        """
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin = self._add_text_plugin(simple_placeholder)

        child_plugin_1 = self._add_child_plugin(
            text_plugin,
            plugin_type='LinkPlugin',
        )

        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin_1)

        child_plugin_2 = self._add_child_plugin(
            text_plugin,
            plugin_type='LinkPlugin',
        )

        text_plugin = self.add_plugin_to_text(text_plugin, child_plugin_2)

        # create a page translation to copy plugins to
        translation = create_title(
            "fr",
            "test-page-fr",
            simple_page,
            slug="test-page-fr"
        )

        self.assertEqual(CMSPlugin.objects.filter(language='en').count(), 3)
        self.assertEqual(CMSPlugin.objects.filter(language=translation.language).count(), 0)

        data = {
            'source_placeholder_id': simple_placeholder.pk,
            'target_placeholder_id': simple_placeholder.pk,
            'target_language': translation.language,
            'source_language': 'en',
        }

        endpoint = admin_reverse('cms_placeholder_copy_plugins')
        endpoint += '?' + urlencode({'cms_path': '/en/'})

        with self.login_user_context(self.user):
            response = self.client.post(endpoint, data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(CMSPlugin.objects.filter(language='en').count(), 3)
            self.assertEqual(CMSPlugin.objects.filter(language=translation.language).count(), 3)

            plugins = list(CMSPlugin.objects.all().order_by('pk'))
            new_plugin = plugins[3].get_plugin_instance()[0]
            idlist = sorted(plugin_tags_to_id_list(new_plugin.body))
            expected = sorted([plugins[4].pk, plugins[5].pk])
            self.assertEqual(idlist, expected)

    def test_copy_plugin_callback(self):
        simple_page = create_page('test page', 'page.html', u'en')
        simple_placeholder = simple_page.get_placeholders('en').get(slot='content')

        text_plugin_1 = self._add_text_plugin(simple_placeholder)

        child_plugin_1_a = self._add_child_plugin(
            text_plugin_1,
            plugin_type='LinkPlugin',
        )

        text_plugin_1 = self.add_plugin_to_text(text_plugin_1, child_plugin_1_a)

        child_plugin_1_b = self._add_child_plugin(
            text_plugin_1,
            plugin_type='LinkPlugin',
        )

        text_plugin_1 = self.add_plugin_to_text(text_plugin_1, child_plugin_1_b)

        text_plugin_2 = copy.copy(text_plugin_1)
        text_plugin_2.pk = None
        text_plugin_2.save()

        child_plugin_2_a = self._add_child_plugin(
            text_plugin_2,
            plugin_type='LinkPlugin',
        )
        child_plugin_2_b = self._add_child_plugin(
            text_plugin_2,
            plugin_type='LinkPlugin',
        )
        source_map = {
            child_plugin_1_a.pk: child_plugin_2_a,
            child_plugin_1_b.pk: child_plugin_2_b,
        }

        TextPlugin.do_post_copy(text_plugin_2, source_map)

        text_plugin_2.refresh_from_db()
        idlist = sorted(plugin_tags_to_id_list(text_plugin_2.body))
        expected = sorted([child_plugin_2_a.pk, child_plugin_2_b.pk])
        self.assertEqual(idlist, expected)

    def test_plugin_tags_to_id_list(self):
        pairs = (
            ('<cms-plugin id="1"></cms-plugin><cms-plugin id="2"></cms-plugin>', [1, 2]),
            ('<cms-plugin alt="<h1>markup</h1>" id="1"></cms-plugin><cms-plugin id="1"></cms-plugin>', [1, 1]),
        )

        for markup, expected in pairs:
            self.assertEqual(plugin_tags_to_id_list(markup), expected)

    def test_text_plugin_xss(self):
        page = create_page('test page', 'page.html', u'en')
        placeholder = page.get_placeholders('en').get(slot='content')
        plugin = add_plugin(placeholder, 'TextPlugin', 'en', body='body')
        endpoint = self.get_change_plugin_uri(plugin)

        with self.login_user_context(self.user):
            data = {
                "body": (
                    "<div onload='do_evil_stuff();'>divcontent</div><a href='javascript:do_evil_stuff()'>acontent</a>"
                )
            }
            response = self.client.post(endpoint, data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.reload(plugin).body, '<div>divcontent</div><a>acontent</a>')


@unittest.skipUnless(
    HAS_DJANGOCMS_TRANSLATIONS and HAS_DJANGOCMS_TRANSFER,
    'Optional dependencies for tests are not installed.'
)
class DjangoCMSTranslationsIntegrationTestCase(BaseTestCase):
    def setUp(self):
        super(DjangoCMSTranslationsIntegrationTestCase, self).setUp()
        self.page = create_page('test page', 'page.html', 'en', published=True)
        self.placeholder = self.page.get_placeholders('en').get(slot='content')

    def _export_page(self):
        return json.loads(export_page(self.page, 'en'))

    def test_textfield_without_children(self):
        raw_content = '<p>Please <a href="http://www.google.com">CLICK ON LINK1</a> to go to link1.</p>'
        add_plugin(self.placeholder, 'TextPlugin', 'en', body=raw_content)

        plugin = self._export_page()[0]['plugins'][0]
        result, children_included_in_this_content = TextPlugin.get_translation_export_content('body', plugin['data'])

        self.assertEquals(result, raw_content)
        self.assertEquals(children_included_in_this_content, [])

        result = TextPlugin.set_translation_import_content(result, plugin)
        self.assertDictEqual(result, {})

    def test_textfield_with_children(self):
        parent = add_plugin(self.placeholder, 'TextPlugin', 'en', body='')
        child1 = add_plugin(self.placeholder, 'DummyLinkPlugin', 'en', target=parent, label='CLICK ON LINK1')
        parent_body = (
            '<p>Please <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}"></cms-plugin> to go to link1.</p>'
        ).format(child1.pk)
        parent.body = parent_body
        parent.save()

        plugin = self._export_page()[0]['plugins'][0]
        result, children_included_in_this_content = TextPlugin.get_translation_export_content('body', plugin['data'])

        expected = (
            parent_body
            .replace('></cms-plugin>', '>CLICK ON LINK1</cms-plugin>', 1)
        )
        self.assertEquals(result, expected)
        self.assertEquals(children_included_in_this_content, [child1.pk])

        result = TextPlugin.set_translation_import_content(result, plugin)
        self.assertDictEqual(result, {child1.pk: 'CLICK ON LINK1'})

    def test_textfield_with_multiple_children(self):
        parent = add_plugin(self.placeholder, 'TextPlugin', 'en', body='')
        child1 = add_plugin(self.placeholder, 'DummyLinkPlugin', 'en', target=parent, label='CLICK ON LINK1')
        child2 = add_plugin(self.placeholder, 'DummyLinkPlugin', 'en', target=parent, label='CLICK ON LINK2')
        parent_body = (
            '<p>Please <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}"></cms-plugin> to go to link1 '
            'or <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}"></cms-plugin> to go to link2.</p>'
        ).format(child1.pk, child2.pk)
        parent.body = parent_body
        parent.save()

        plugin = self._export_page()[0]['plugins'][0]
        result, children_included_in_this_content = TextPlugin.get_translation_export_content('body', plugin['data'])

        expected = (
            parent_body
            .replace('></cms-plugin>', '>CLICK ON LINK1</cms-plugin>', 1)
            .replace('></cms-plugin>', '>CLICK ON LINK2</cms-plugin>', 1)
        )
        self.assertEquals(result, expected)
        self.assertEquals(children_included_in_this_content, [child1.pk, child2.pk])

        result = TextPlugin.set_translation_import_content(result, plugin)
        self.assertDictEqual(result, {child1.pk: 'CLICK ON LINK1', child2.pk: 'CLICK ON LINK2'})

    def test_textfield_with_multiple_children_one_deleted(self):
        parent = add_plugin(self.placeholder, 'TextPlugin', 'en', body='')
        child1 = add_plugin(self.placeholder, 'DummyLinkPlugin', 'en', target=parent, label='CLICK ON LINK1')
        child2 = add_plugin(self.placeholder, 'DummyLinkPlugin', 'en', target=parent, label='CLICK ON LINK2')
        parent_body = (
            '<p>Please <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}"></cms-plugin> to go to link1 '
            'or <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}"></cms-plugin> to go to link2.</p>'
        ).format(child1.pk, child2.pk)
        parent.body = parent_body
        parent.save()

        plugin = self._export_page()[0]['plugins'][0]

        child1.delete()

        result, children_included_in_this_content = TextPlugin.get_translation_export_content('body', plugin['data'])

        expected = (
            '<p>Please  to go to link1 '
            'or <cms-plugin alt="Dummy Link Plugin - dummy link object "'
            'title="Dummy Link Plugin - dummy link object" id="{}">CLICK ON LINK2</cms-plugin> to go to link2.</p>'
        ).format(child2.pk)
        self.assertEquals(result, expected)
        self.assertEquals(children_included_in_this_content, [child2.pk])

        result = TextPlugin.set_translation_import_content(result, plugin)
        self.assertDictEqual(result, {child2.pk: 'CLICK ON LINK2'})

    def test_textfield_with_untranslatable_children(self):
        parent = add_plugin(self.placeholder, 'TextPlugin', 'en', body='')
        child1 = add_plugin(self.placeholder, 'DummySpacerPlugin', 'en', target=parent)
        parent_body = (
            '<p>This is cool <cms-plugin alt="Dummy Spacer Plugin - dummy spacer object "'
            'title="Dummy Spacer Plugin - dummy spacer object" id="{}"></cms-plugin> this is nice</p>'
        ).format(child1.pk)
        parent.body = parent_body
        parent.save()

        plugin = self._export_page()[0]['plugins'][0]
        result, children_included_in_this_content = TextPlugin.get_translation_export_content('body', plugin['data'])

        expected = (
            parent_body
        )
        self.assertEquals(result, expected)
        self.assertEquals(children_included_in_this_content, [child1.pk])

        result = TextPlugin.set_translation_import_content(result, plugin)
        self.assertDictEqual(result, {child1.pk: ''})
