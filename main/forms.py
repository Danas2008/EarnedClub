from django import forms
from django.contrib.auth.models import User


class FlexibleUsernameCreationForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        help_text="Use the public username you want shown on Earned Club.",
    )
    password1 = forms.CharField(strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(strip=False, widget=forms.PasswordInput)

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise forms.ValidationError("Username is required.")
        if any(ord(character) < 32 for character in username):
            raise forms.ValidationError("Username cannot contain hidden control characters.")
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two password fields did not match.")
        if password1 and len(password1) < 6:
            self.add_error("password1", "Password must contain at least 6 characters.")
        return cleaned_data

    def save(self, commit=True):
        user = User(username=self.cleaned_data["username"])
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
