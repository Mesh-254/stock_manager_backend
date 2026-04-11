"""

Enhanced admin.py with dashboard callback integration.

This file should be placed in your main Django app and registers

the dashboard callback with the Unfold configuration.

It also handles HTMX POST requests for dynamic dashboard filtering.

"""

from django.contrib import admin

from django.http import HttpResponse

from django.template.loader import render_to_string

from django.shortcuts import render

from unfold.admin import UnfoldAdminSite

from django.utils.translation import gettext_lazy as _

class SchoolShopAdminSite(UnfoldAdminSite):

    """

    Enhanced admin site with full dashboard callback and HTMX support.

    """

    

    site_header = _("School Shop Inventory Manager")

    site_title = _("Shop Inventory")

    index_title = _("Dashboard Overview")

    

    def index(self, request, extra_context=None):

        """

        Enhanced index view that:

        1. Calls the dashboard callback to populate context

        2. Handles HTMX POST requests for date filtering

        3. Returns partial HTML for HTMX or full page for regular requests

        """

        extra_context = extra_context or {}

        

        # ===== CALL DASHBOARD CALLBACK =====

        from django.conf import settings

        import importlib

        

        dashboard_callback_path = settings.UNFOLD.get('DASHBOARD_CALLBACK')

        if dashboard_callback_path:

            # Dynamically import and call the callback

            module_path, func_name = dashboard_callback_path.rsplit('.', 1)

            module = importlib.import_module(module_path)

            callback = getattr(module, func_name)

            extra_context = callback(request, extra_context)

        

        # ===== HANDLE HTMX REQUESTS =====

        if request.method == 'POST' and request.headers.get('HX-Request'):

            # HTMX request detected - return only dashboard content partial

            # This allows the date filter to update content without page reload

            template_name = 'admin/dashboard_content.html'

            html = render_to_string(template_name, extra_context, request=request)

            return HttpResponse(html)

        

        # ===== REGULAR REQUEST =====

        # Call parent to render full admin index page

        return super().index(request, extra_context=extra_context)

# Register custom admin site

# admin.site = SchoolShopAdminSite(name='admin')