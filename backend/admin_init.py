"""

Unfold Admin Site initialization.

This file creates the custom admin site that inherits from UnfoldAdminSite,

providing enhanced dashboard capabilities and styling through Unfold.

Import this in your main Django app's apps.py or urls.py to register

the custom admin site globally.

"""

from django.contrib import admin

from django.utils.translation import gettext_lazy as _

from unfold.admin import UnfoldAdminSite

class SchoolShopAdminSite(UnfoldAdminSite):

    """

    Custom admin site for School Shop Inventory System.

    

    Inherits from UnfoldAdminSite to provide:

    - Modern, responsive admin interface

    - Dark mode support

    - Dashboard callback integration

    - Tailwind CSS styling

    

    Configuration is done via Django settings.UNFOLD dictionary.

    """

    

    # Customize the header and titles

    site_header = _("School Shop Inventory Manager")

    site_title = _("Shop Inventory")

    index_title = _("Dashboard Overview")

    

    def index(self, request, extra_context=None):

        """

        Override index view to handle HTMX requests for dashboard filtering.

        

        This method intercepts both regular GET requests and HTMX POST requests,

        allowing the dashboard to be updated without full page reload when

        date filters are applied.

        

        Args:

            request: HttpRequest object

            extra_context: Optional context dictionary

        

        Returns:

            Response with dashboard template

        """

        extra_context = extra_context or {}

        

        # Call parent index method to get base context

        response = super().index(request, extra_context=extra_context)

        

        return response