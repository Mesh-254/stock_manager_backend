# accounts/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views


# Create a router and register our viewset with it.
router = DefaultRouter()

router.register(r'users', views.UserViewSet, basename='user')


urlpatterns = [
    path('', include(router.urls)),
    path('check-email/', views.check_email, name='check_email'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),

    path('verify-email/<uuid:token>/', views.VerifyEmailView.as_view(), name='verify_email'),
    path('resend-confirmation/', views.resend_confirmation_email, name='resend_confirmation'),

    path('password-reset/', views.PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password-reset-confirm/<uuid:token>/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('admin-reset-password/<uuid:user_id>/', views.AdminPasswordResetView.as_view(), name='admin-reset-password'),
]
