from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice


class CounselorTwoFactorMiddleware:
    """Counselors must finish two-factor login before reaching any page."""

    EXEMPT_URL_NAMES = ("login", "logout", "two_factor_setup", "two_factor_verify")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            settings.REQUIRE_COUNSELOR_2FA
            and user.is_authenticated
            and user.requires_two_factor
            and not user.is_verified()
            and not request.path.startswith("/" + settings.STATIC_URL.lstrip("/"))
            and request.path not in {reverse(name) for name in self.EXEMPT_URL_NAMES}
        ):
            if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
                return redirect("two_factor_verify")
            return redirect("two_factor_setup")
        return self.get_response(request)
