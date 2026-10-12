from django import forms
from django.contrib.auth import password_validation

from .models import User


class AcceptInviteForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, strip=False)
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput, strip=False)

    def __init__(self, *args, email, **kwargs):
        self.email = email
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The passwords do not match.")
        if p1:
            temp_user = User(email=self.email, first_name=cleaned.get("first_name", ""), last_name=cleaned.get("last_name", ""))
            try:
                password_validation.validate_password(p1, temp_user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class TokenForm(forms.Form):
    token = forms.CharField(
        label="Code",
        max_length=16,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "autofocus": True}),
    )
