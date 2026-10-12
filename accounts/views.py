import base64

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp import match_token
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
import qrcode
import qrcode.image.svg

from core import audit

from .forms import AcceptInviteForm, TokenForm
from .models import Invite, User

BACKUP_CODE_COUNT = 10


@require_http_methods(["GET", "POST"])
def accept_invite(request, token):
    invite = Invite.find_valid(token)
    if invite is None:
        return render(request, "accounts/invite_invalid.html", status=404)

    existing = User.objects.filter(email__iexact=invite.email).first()
    if existing is not None:
        # A parent who already has an account (e.g. a second child) is simply linked.
        if existing.role == User.Role.PARENT and invite.role == User.Role.PARENT:
            with transaction.atomic():
                invite.student.parents.add(existing)
                invite.accepted_at = timezone.now()
                invite.save(update_fields=["accepted_at"])
            audit.log(request, audit.Action.UPDATE, invite.student, user=existing, detail="Parent linked via invite")
            messages.success(request, f"{invite.student} has been added to your account. Please log in.")
            return redirect("login")
        return render(request, "accounts/invite_invalid.html", {"reason": "exists"}, status=400)

    if invite.role == User.Role.STUDENT and invite.student.user_id is not None:
        return render(request, "accounts/invite_invalid.html", {"reason": "student_linked"}, status=400)

    form = AcceptInviteForm(request.POST or None, email=invite.email)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(
                email=invite.email,
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                role=invite.role,
            )
            if invite.role == User.Role.STUDENT:
                invite.student.user = user
                invite.student.save(update_fields=["user"])
            else:
                invite.student.parents.add(user)
            invite.accepted_at = timezone.now()
            invite.save(update_fields=["accepted_at"])
        audit.log(request, audit.Action.CREATE, user, student=invite.student, user=user, detail="Account created from invite")
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("home")
    return render(request, "accounts/accept_invite.html", {"form": form, "invite": invite})


def _qr_svg(data):
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    return image.to_string(encoding="unicode")


@login_required
@require_http_methods(["GET", "POST"])
def two_factor_setup(request):
    user = request.user
    if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
        return redirect("two_factor_verify")
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=False)

    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if device.verify_token(form.cleaned_data["token"].replace(" ", "")):
            device.confirmed = True
            device.save()
            otp_login(request, device)
            codes = _new_backup_codes(user)
            audit.log(request, audit.Action.TWO_FACTOR, detail="Authenticator app set up")
            return render(request, "accounts/backup_codes.html", {"codes": codes})
        form.add_error("token", "That code didn't work. Check your phone's clock and try the newest code.")
    return render(
        request,
        "accounts/two_factor_setup.html",
        {"form": form, "qr_svg": _qr_svg(device.config_url), "secret": _base32_secret(device)},
    )


@login_required
@require_http_methods(["GET", "POST"])
def two_factor_verify(request):
    if request.user.is_verified():
        return redirect("home")
    form = TokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        device = match_token(request.user, form.cleaned_data["token"].replace(" ", ""))
        if device is not None:
            otp_login(request, device)
            return redirect("home")
        audit.log(request, audit.Action.TWO_FACTOR, detail="Wrong two-factor code")
        form.add_error("token", "That code didn't work.")
    return render(request, "accounts/two_factor_verify.html", {"form": form})


def _new_backup_codes(user):
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name="Backup codes")
    codes = [StaticToken.random_token() for _ in range(BACKUP_CODE_COUNT)]
    for code in codes:
        device.token_set.create(token=code)
    return codes


def _base32_secret(device):
    return base64.b32encode(device.bin_key).decode("ascii")
