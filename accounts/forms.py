from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError


class EmailOrUsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "Username or email"}),
    )

    def clean(self):
        login = self.cleaned_data.get("username", "").strip()
        password = self.cleaned_data.get("password")
        if login and password:
            User = get_user_model()
            if "@" in login:
                matched = User.objects.filter(email__iexact=login).first()
                if matched:
                    login = matched.username
            self.user_cache = authenticate(self.request, username=login, password=password)
            if self.user_cache is None:
                raise self.get_invalid_login_error()
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email already exists.")
        return email
