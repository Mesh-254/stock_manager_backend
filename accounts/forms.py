from allauth.account.forms import SignupForm


class CustomSignupForm(SignupForm):
    """Remove any username field that allauth might try to add."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "username" in self.fields:
            del self.fields["username"]
